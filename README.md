# Physics-Informed-Digital-Twin-for-Crack-Debonding-Discrimination
Fiber debonding can mimic structural crack signatures in distributed optical-fiber sensing. A physics-informed digital twin jointly diagnoses girder cracks and bond loss using two sensing routes and multiple loads, achieving 96.25% balanced accuracy while identifying conditions where the faults become indistinguishable.

All observations are synthetic. The numerical asset is an equivalent rectangular, simply supported 8 m girder strip; it is not a surveyed bridge or a detailed welded I-girder. The code uses Python beam mechanics and fibre rod finite elements. No field tests, laboratory measurements, COMSOL runs or hardware detection limits are represented as completed work. The study was not prospectively registered.

The complete numerical run took 462.48 seconds on the original Python 3.12.14 environment. The base random seed is 20261010. Data generation, forest training, noise challenges, mismatch challenges and bootstrap resampling use explicit derived seeds in the scripts. Floating-point libraries and package changes may slightly alter numerical fits; execution timings are not deterministic. There is one trained seed per forest, not a retraining-variability experiment.


| Array | Shape | Meaning and units |
|---|---|---|
| `strain` | windows × 2 × 3 × 297 | Temperature-compensated, finite-gauge observation profiles; microstrain |
| `temperature_coeff` | windows × 3 × 3 | Estimated reference-temperature coefficients for constant, linear and sine basis functions, for each load; kelvin |
| `label` | windows | Integer class in the stated order |
| `x` | 297 | Gauge centres along the girder; metres |
| `loads` | 3 | Diagnostic load positions; metres |

Reference-temperature coefficients are estimates supplied to inversion, not the latent true coefficients. The 50 mm gauges overlap at a 25 mm sample pitch. Gauges within an acquisition window are not independent benchmark cases.

## Principal executed outcomes

| Quantity | Result |
|---|---|
| Two-route, three-load balanced accuracy | 96.25% (462/480) |
| Morphology forest balanced accuracy | 92.08% (442/480) |
| Single-route balanced accuracy | 87.08% |
| Two-route, single-load balanced accuracy | 94.38% |
| Paired accuracy improvement over morphology forest | 4.17 percentage points; 95% case-bootstrap interval 2.29–6.25 |
| Nominal gate acceptance | 458/480; 14 wrong accepted labels |
| Conditional crack-centre/depth mean absolute errors | 1.28 mm / 0.29 mm |
| Combined model-mismatch balanced accuracy | 85.00% |
| Shared-debond rejection | 59/64; all five acceptances remain outside the catalogue |

These results characterize this synthetic benchmark and its assumptions. They do not establish service prevalence, millimetre hardware resolution, remaining bridge life, universal novelty or journal acceptance. Numerical truth and inverse models differ in discretization and smoothing but share reduced mechanics. Independent physical validation remains necessary for deployment claims.
