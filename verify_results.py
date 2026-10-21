"""Check saved benchmark evidence without repeating generation or inverse fits."""
from pathlib import Path
import csv
import hashlib
import json
import re
import zipfile
import xml.etree.ElementTree as ET
import numpy as np

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / 'results'
S = json.loads((RESULTS / 'summary.json').read_text())
CHECKS = []


def check(name, condition, detail=None):
    result = {'check': name, 'passed': bool(condition)}
    if detail is not None:
        result['detail'] = detail
    CHECKS.append(result)
    if not condition:
        raise AssertionError(name)


def rows(name):
    with (RESULTS / name).open(newline='') as handle:
        return list(csv.DictReader(handle))


def near(actual, expected):
    return np.allclose(actual, expected, rtol=1e-9, atol=1e-12)


def values(data, key, cast=float):
    return np.array([cast(r[key]) for r in data])


def metric_check(name, truth, prediction, expected, weights=None):
    cm = np.zeros((4, 4), dtype=int)
    np.add.at(cm, (truth, prediction), 1)
    recall = np.divide(cm.diagonal(), cm.sum(axis=1), out=np.zeros(4), where=cm.sum(axis=1) > 0)
    present = cm.sum(axis=1) > 0
    f1_denominator = cm.sum(axis=0) + cm.sum(axis=1)
    f1 = np.divide(2 * cm.diagonal(), f1_denominator, out=np.zeros(4), where=f1_denominator > 0)
    metrics = {'accuracy': float(np.mean(truth == prediction)),
               'balanced_accuracy': float(np.mean(recall[present])),
               'macro_f1': float(np.mean(f1[present | (cm.sum(axis=0) > 0)]))}
    if np.any(truth == 0):
        metrics['healthy_false_alarm'] = float(np.mean(prediction[truth == 0] != 0))
    check(name + ': confusion counts', cm.tolist() == expected['confusion'])
    check(name + ': classification metrics', all(near(value, expected[key]) for key, value in metrics.items()))
    if weights is not None:
        check(name + ': normalized weights', np.isfinite(weights).all() and near(weights.sum(axis=1), 1) and (weights >= 0).all())
        brier = float(np.mean(np.sum((weights - np.eye(4)[truth])**2, axis=1)))
        check(name + ': multiclass Brier score', near(brier, expected['multiclass_brier']))


def weight_array(data):
    return np.column_stack([values(data, 'w' + str(k)) for k in range(4)])


def gate_check(name, data, truth, expected):
    pred = values(data, 'prediction', int)
    accepted = (values(data, 'confidence') >= .95) & (values(data, 'red_chi2') <= S['discrepancy_threshold'])
    counts = {'accepted': int(accepted.sum()), 'rejected': int((~accepted).sum()),
              'wrong_confident': int(np.sum(accepted & (pred != truth)))}
    check(name + ': gate counts', all(value == expected[key] for key, value in counts.items()))
    check(name + ': gate rates', near(accepted.mean(), expected['coverage']) and near(np.mean(pred[accepted] == truth[accepted]), expected['selective_accuracy']))


def main():
    bands = {}
    for split, count in [('train', 1200), ('val', 240), ('test', 480)]:
        data = rows(split + '_configurations.csv')
        z = np.load(RESULTS / (split + '_observations.npz'))
        truth = values(data, 'class', int)
        check(split + ': shapes and finite observations', z['strain'].shape == (count, 2, 3, 297) and z['temperature_coeff'].shape == (count, 3, 3) and np.isfinite(z['strain']).all() and np.isfinite(z['temperature_coeff']).all())
        check(split + ': balanced classes and aligned order', np.array_equal(np.bincount(truth, minlength=4), np.full(4, count // 4)) and np.array_equal(truth, z['label']))
        check(split + ': gauge and load coordinates', near(z['x'], .3 + .025 * np.arange(297)) and near(z['loads'], [2, 4, 6]))
        centres = np.array([float(row[k]) for row in data for k in ['xc', 'xd'] if row[k]])
        band = np.floor((centres - .8) / .2).astype(int)
        bands[split] = set(band.tolist())
        check(split + ': spatial-band allocation', bool(np.all((band % 4 == 3) == (split == 'test'))))
    check('held-out damage bands disjoint', bands['test'].isdisjoint(bands['train'] | bands['val']))
    data = rows('test_predictions.csv')
    truth = values(data, 'truth', int)
    check('test prediction order aligned with data', np.array_equal(truth, values(rows('test_configurations.csv'), 'class', int)))
    for name, column in [('Raw-profile random forest', 'raw_rf_prediction'), ('Morphology random forest', 'shape_rf_prediction'), ('Physics twin two routes three loads', 'prediction')]:
        metric_check(name, truth, values(data, column, int), S['main'][name], weight_array(data) if column == 'prediction' else None)
    gate_check('nominal test', data, truth, S['gated'])
    for name, file in [('One route three loads', 'one_route_three_loads.csv'), ('Two routes one load', 'two_routes_one_load.csv')]:
        ablation = rows(file)
        metric_check(name, truth, values(ablation, 'prediction', int), S['ablations'][name], weight_array(ablation))
    parameters = rows('parameter_estimates.csv')
    for expected in S['uncertainty']:
        key = expected['parameter']
        subset = [row for row in parameters if row['parameter'] == key]
        true_value, estimate = values(subset, 'truth'), values(subset, 'estimate')
        err = estimate - true_value
        lower, upper = values(subset, 'interval_lower'), values(subset, 'interval_upper')
        hit = (true_value >= lower) & (true_value <= upper)
        computed = {'mae': np.mean(abs(err)), 'rmse': np.sqrt(np.mean(err**2)), 'coverage': np.mean(hit), 'median_width': np.median(upper - lower)}
        check(key + ': conditional parameters and intervals', len(subset) == expected['n'] and np.array_equal(hit.astype(int), values(subset, 'covered', int)) and all(near(value, expected[k]) for k, value in computed.items()))
        check(key + ': calibration scales applied', near((upper - lower) / 2, S['calibration_scale'][key] * values(subset, 'standard_error')))
        ids = values(subset, 'id', int)
        check(key + ': correct-class conditioning', np.all(values(data, 'prediction', int)[ids] == truth[ids]))
    robust = rows('robustness_predictions.csv')
    for expected in S['noise']:
        subset = [row for row in robust if row['scenario'] == 'noise' and float(row['setting']) == expected['sigma']]
        y, p = values(subset, 'truth', int), values(subset, 'prediction', int)
        metric_check('noise ' + str(expected['sigma']), y, p, expected)
        check('noise ' + str(expected['sigma']) + ': count', len(subset) == 80 and int(np.sum(y == p)) == expected['correct'])
    for scenario, key in [('mismatch', 'mismatch'), ('shared_debond', 'shared')]:
        subset = [row for row in robust if row['scenario'] == scenario]
        y = values(subset, 'truth', int)
        metric_check(scenario + ' coarse-label summary', y, values(subset, 'prediction', int), S[key])
        gate_check(scenario, subset, y, S[key + '_gate'])
    subset = rows('temperature_omission.csv')
    y = values(subset, 'truth', int)
    metric_check('temperature omission', y, values(subset, 'prediction', int), S['no_temperature'])
    gate_check('temperature omission', subset, y, S['no_temperature_gate'])
    refinement = [row for row in rows('verification.csv') if row['component'] == 'Consistent rod FE']
    check('consistent fibre mesh refinement', len(refinement) == 4 and np.all(np.diff(values(refinement, 'relative_L2_error')) < 0))
    z = np.load(RESULTS / 'blind_spot.npz')
    blind_difference = float(np.max(abs(z['bonded'] - z['debonded'])))
    check('blind-spot result', near(blind_difference, S['four_point_blind_max_difference_microstrain']) and blind_difference < 1e-8)
    trace = rows('sequential_trace.csv')
    z = np.load(RESULTS / 'sequential_observations.npz')
    y = np.where(values(trace, 'true_debond_mm') > 0, 3, 1)
    check('chronological stream shape and order', z['strain'].shape == (41, 2, 3, 297) and np.isfinite(z['strain']).all() and near(z['cycles'], values(trace, 'cycles')))
    check('chronological stream class and gate counts', int(np.sum(values(trace, 'filtered_prediction', int) == y)) == 40 and int(values(trace, 'accepted', int).sum()) == S['sequential_accepted'] == 38)
    posterior = np.column_stack([values(trace, 'posterior_' + str(k)) for k in range(4)])
    check('chronological filtered weights', np.isfinite(posterior).all() and near(posterior.sum(axis=1), 1) and np.array_equal(posterior.argmax(axis=1), values(trace, 'filtered_prediction', int)))
    delta = np.loadtxt(RESULTS / 'paired_bootstrap_differences.csv', delimiter=',', skiprows=1)
    bootstrap = json.loads((RESULTS / 'bootstrap_summary.json').read_text())
    check('retained paired bootstrap interval', delta.shape == (2000,) and near(np.quantile(delta, [.025, .975]), bootstrap['paired_difference_physics_minus_morphology']['ci']))
    document = ROOT.parent.parent / 'output' / 'Bridge_Girder_Physics_Informed_Digital_Twin.docx'
    document_status = 'optional document absent; run builder to verify it'
    if document.exists():
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main', 'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math'}
        with zipfile.ZipFile(document) as package:
            check('Word package integrity', package.testzip() is None)
            xml = ET.fromstring(package.read('word/document.xml'))
            equation_numbers = []
            for para in xml.findall('.//w:body/w:p', ns):
                if para.find('.//m:oMath', ns) is not None:
                    text = ''.join(para.itertext())
                    match = re.search(r'\((\d+)\)\s*$', text)
                    if match:
                        equation_numbers.append(int(match[1]))
            check('sequential numbered editable equations', equation_numbers == list(range(1, 29)) and len(xml.findall('.//m:oMath', ns)) == 52)
            check('Word table and image inventory', len(xml.findall('.//w:tbl', ns)) == 8 and len([name for name in package.namelist() if name.startswith('word/media/')]) == 12)
        document_status = 'verified: 28 numbered equations, 52 math objects, 8 tables, 12 figures'
    report = {'status': 'passed', 'scope': 'consistency of retained synthetic outputs; not physical validation or a second full numerical run', 'checks_passed': len(CHECKS), 'checks': CHECKS, 'optional_word_check': document_status, 'summary_sha256': hashlib.sha256((RESULTS / 'summary.json').read_bytes()).hexdigest()}
    (ROOT / 'verification_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'checks'}, indent=2))


if __name__ == '__main__':
    main()
