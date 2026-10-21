"""Execute the fixed-seed synthetic benchmark and save numerical outputs."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import sys,json,time,csv,platform,importlib.metadata
from pathlib import Path
from dataclasses import asdict
import numpy as np
from scipy.stats import norm
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix,balanced_accuracy_score,f1_score,brier_score_loss
from physics import *

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results'; OUT.mkdir(exist_ok=True)
RNG=np.random.default_rng(C.seed)

def csvwrite(name,rows):
    rows=list(rows)
    if not rows:return
    with (OUT/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def clean_json(obj):
    if isinstance(obj,np.ndarray):return obj.tolist()
    if isinstance(obj,(np.integer,np.floating)):return obj.item()
    if isinstance(obj,dict):return {k:clean_json(v) for k,v in obj.items() if k!='jac'}
    if isinstance(obj,(list,tuple)):return [clean_json(v) for v in obj]
    return obj

def pos(rng,split):
    allowed=np.array([i for i in range(32) if (i%4==3)==(split=='test')])
    b=int(rng.choice(allowed));return .8+.2*b+rng.uniform(.015,.185)

def parameter(rng,label,split):
    xc=pos(rng,split); xd=pos(rng,split)
    if label==3 and rng.random()<.55:
        # Half of the joint cases lie in the same location block, including overlap.
        base=.8+.2*int((xc-.8)/.2)
        xd=float(np.clip(xc+rng.normal(0,.035),base+.015,base+.185))
    return {'xc':xc if label in (1,3) else None,
            'r':float(rng.uniform(.012,.16)) if label in (1,3) else 0.,
            'xd':xd if label in (2,3) else None,
            'ld':float(rng.uniform(.04,.60)) if label in (2,3) else 0.}

def dataset(name,n_per_class):
    rng=np.random.default_rng(C.seed+{'train':1,'val':2,'test':3}[name])
    Y=[];T=[];P=[];labels=[]
    for label in range(4):
        for i in range(n_per_class):
            p=parameter(rng,label,name)
            y,raw,temp,tref,coeff,tc=optical_observation(p,rng)
            Y.append(y);T.append(coeff);P.append(p);labels.append(label)
    Y=np.array(Y);T=np.array(T);labels=np.array(labels)
    np.savez_compressed(OUT/f'{name}_observations.npz',strain=Y,temperature_coeff=T,label=labels,x=XOBS,loads=LOADS)
    csvwrite(f'{name}_configurations.csv',[{'id':f'{name}_{j:04d}','class':int(l),**p} for j,(l,p) in enumerate(zip(labels,P))])
    return Y,T,P,labels

def shape_features(data):
    # Statistical morphology only: no mechanical forward equations in classifier.
    f=[]
    for y in data:
        yy=y-forward()
        signals=np.concatenate([yy,((yy[0]+yy[1])/2)[None],(yy[0]-yy[1])[None]],axis=0)
        one=[]
        for a in signals.reshape(-1,len(XOBS)):
            a=a-a.mean()
            one.extend([np.max(a),np.min(a),np.std(a),np.quantile(a,.95),np.quantile(a,.05),
                        np.mean(abs(a)),np.max(abs(np.diff(a))),np.mean(np.diff(a)**2),
                        np.mean(a**3)/(np.std(a)**3+1e-12),np.mean(a**4)/(np.std(a)**4+1e-12)])
        f.append(one)
    return np.asarray(f)

def execute_fits(Y,T,single=False,one_load=False,no_temp=False,sigma=C.sigma,tag=''):
    loads=np.array([4.]) if one_load else LOADS
    inv=Inverse(loads,sigma,single)
    rows=[];full=[];timings=[]
    for i,(y,t) in enumerate(zip(Y,T)):
        if one_load:y=y[:,1:2];t=t[1:2]
        inv.set_temperature(None if no_temp else t)
        start=time.perf_counter();r=inv.fit(y,details=True);timings.append(time.perf_counter()-start)
        rows.append({'id':i,'prediction':r['prediction'],'confidence':r['confidence'],'red_chi2':r['red_chi2'],
                     'time_s':timings[-1],**{f'w{j}':v for j,v in enumerate(r['weights'])}})
        full.append(r)
        if (i+1)%80==0:print(tag,'fits',i+1,'/',len(Y),flush=True)
    return rows,full,timings

def chosen_parameters(result,h=None):
    h=result['prediction'] if h is None else h
    fit=result['fits'][h];p=fit['p'];out={};errs={}
    names={0:[],1:['xc','r'],2:['xd','ld'],3:['xc','r','xd','ld']}[h]
    if fit['jac'] is not None:
        cov=np.linalg.pinv(fit['jac'].T@fit['jac'],rcond=1e-10)
        se=np.sqrt(np.maximum(np.diag(cov),0))
        for name,v,s in zip(names,p,se):out[name]=float(v);errs[name]=float(s)
    return out,errs

def calibration(P,labels,results):
    scores={k:[] for k in ['xc','r','xd','ld']}
    for p,l,res in zip(P,labels,results):
        if res['prediction']!=l:continue
        pred,se=chosen_parameters(res)
        for k in pred:
            if se[k]>1e-12:scores[k].append(abs(pred[k]-p[k])/se[k])
    scale={}
    for k,s in scores.items():
        ss=np.sort(s);idx=min(len(ss)-1,int(np.ceil(.95*(len(ss)+1)))-1)
        scale[k]=max(1.96,float(ss[idx]))
    # Validation-set order statistic for a 99% discrepancy acceptance threshold.
    red=np.sort([r['red_chi2'] for r in results]);idx=min(len(red)-1,int(np.ceil(.99*(len(red)+1)))-1)
    return scale,float(red[idx]),{k:len(v) for k,v in scores.items()}

def metrics(labels,pred,weights=None):
    labels=np.asarray(labels);pred=np.asarray(pred)
    m={'n':len(labels),'accuracy':float(np.mean(pred==labels)),
       'balanced_accuracy':float(balanced_accuracy_score(labels,pred)),
       'macro_f1':float(f1_score(labels,pred,average='macro')),
       'healthy_false_alarm':float(np.mean(pred[labels==0]!=0)) if np.any(labels==0) else None,
       'confusion':confusion_matrix(labels,pred,labels=[0,1,2,3]).tolist()}
    if weights is not None:
        w=np.asarray(weights);truth=np.eye(4)[labels]
        m['multiclass_brier']=float(np.mean(np.sum((w-truth)**2,axis=1)))
    return m

def gated_metrics(labels,results,threshold):
    pred=np.array([r['prediction'] for r in results]);conf=np.array([r['confidence'] for r in results]);red=np.array([r['red_chi2'] for r in results])
    gate=(conf>=.95)&(red<=threshold)
    return {'accepted':int(gate.sum()),'coverage':float(gate.mean()),'selective_accuracy':float(np.mean(pred[gate]==labels[gate])) if gate.any() else None,
            'wrong_confident':int(np.sum(gate&(pred!=labels))), 'rejected':int((~gate).sum())},gate

def uncertainty_table(P,labels,results,scale):
    records=[];summary=[]
    for k in ['xc','r','xd','ld']:
        err=[];hit=[];width=[]
        for j,(p,l,r) in enumerate(zip(P,labels,results)):
            # Conditional on correctly identified hypothesis, explicitly reported.
            if r['prediction']!=l:continue
            pred,se=chosen_parameters(r)
            if k not in pred:continue
            delta=pred[k]-p[k];half=scale[k]*se[k]
            err.append(delta);hit.append(abs(delta)<=half);width.append(2*half)
            records.append({'id':j,'parameter':k,'truth':p[k],'estimate':pred[k],'standard_error':se[k],
                            'interval_lower':pred[k]-half,'interval_upper':pred[k]+half,'covered':int(abs(delta)<=half)})
        summary.append({'parameter':k,'n':len(err),'mae':float(np.mean(abs(np.array(err)))),
                        'rmse':float(np.sqrt(np.mean(np.array(err)**2))),'coverage':float(np.mean(hit)),
                        'median_width':float(np.median(width))})
    csvwrite('parameter_estimates.csv',records);return summary

def verification():
    rows=[]
    x=np.linspace(.01,7.99,503)
    analytic=host_displacement(x,3.25,.10,loads=np.array([4.]))[:,0]/(.3)
    for ne in [10,20,40,80]:
        nd,z,cr,ex=beam_fe(ne=ne)
        fe=beam_fe_rotation(x,nd,z,cr,ex)
        rows.append({'component':'Hermite beam','mesh':ne,'relative_L2_error':np.linalg.norm(fe-analytic)/np.linalg.norm(analytic)})
    old=C.truth_dx
    C.truth_dx=.00125
    ref=forward(3.27,.065,3.44,.30,truth=True)
    for dx in [.020,.010,.005,.0025]:
        C.truth_dx=dx;sol=forward(3.27,.065,3.44,.30,truth=True)
        rows.append({'component':'Consistent rod FE','mesh':dx,'relative_L2_error':np.linalg.norm(sol-ref)/np.linalg.norm(ref)})
    C.truth_dx=old
    inv=forward(3.27,.065,3.44,.30)
    rows.append({'component':'Inverse discretisation','mesh':C.inverse_dx,'relative_L2_error':np.linalg.norm(inv-ref)/np.linalg.norm(ref)})
    csvwrite('verification.csv',rows)
    # Analytic uniform-strain solution under end displacement compatibility.
    xx=np.linspace(0,8,3201); uh=(110e-6*xx)[:,None]
    uf=rod_solve(xx,uh,4.,.40,truth=True)
    strain=sample_strain(xx,uf)
    # End boundary effects are excluded by a 1 m margin.
    mask=(XOBS>1)&(XOBS<7)
    check=float(np.max(abs(strain[0,mask]-110)))
    # Four-point bending: central constant moment hides a debond around x=4.
    uh=host_displacement(xx,loads=np.array([2.,6.])).sum(axis=1,keepdims=True)
    bonded=sample_strain(xx,rod_solve(xx,uh,truth=True))[0]
    damaged=sample_strain(xx,rod_solve(xx,uh,4.,.40,truth=True))[0]
    blind=float(np.max(abs(bonded-damaged)))
    np.savez_compressed(OUT/'blind_spot.npz',x=XOBS,bonded=bonded,debonded=damaged)
    return rows,check,blind

def identifiability():
    records=[]
    for single in [True,False]:
        for one in [True,False]:
            inv=Inverse(np.array([4.]) if one else LOADS,single=single)
            for sep in [0.,.025,.05,.10,.20,.40,.80]:
                for ld in [.05,.10,.20,.40,.60]:
                    p=np.array([3.25,.065,3.25+sep,ld]);steps=np.array([.001,1e-4,.001,.001]);scale=np.array([.10,.02,.10,.10])
                    J=[]
                    for j in range(4):
                        a=p.copy();b=p.copy();a[j]+=steps[j];b[j]-=steps[j]
                        J.append(inv.project((inv.prediction(3,a)-inv.prediction(3,b))/(2*steps[j])).ravel()*scale[j])
                    sv=np.linalg.svd(np.array(J).T,compute_uv=False)
                    records.append({'routes':1 if single else 2,'loads':1 if one else 3,'separation_m':sep,'debond_m':ld,
                                    'sigma_min':float(sv[-1]),'sigma_max':float(sv[0]),'ratio':float(sv[-1]/sv[0])})
    csvwrite('identifiability.csv',records)

def main():
    start=time.perf_counter();print('Starting coupled benchmark',flush=True)
    vr,uniform,blind=verification();identifiability()
    train=dataset('train',300);print('1200 training configurations generated',flush=True)
    val=dataset('val',60);test=dataset('test',120);print('Validation and blocked-location test generated',flush=True)
    Ytr,Ttr,Ptr,Ltr=train;Yv,Tv,Pv,Lv=val;Yt,Tt,Pt,Lt=test
    inv=Inverse();Xtr=np.array([inv.project(y-inv.healthy).ravel() for y in Ytr]);Xv=np.array([inv.project(y-inv.healthy).ravel() for y in Yv]);Xt=np.array([inv.project(y-inv.healthy).ravel() for y in Yt])
    rfraw=RandomForestClassifier(n_estimators=400,min_samples_leaf=2,max_features='sqrt',random_state=C.seed,n_jobs=1)
    rfraw.fit(Xtr,Ltr)
    rfshape=RandomForestClassifier(n_estimators=400,min_samples_leaf=2,max_features=.6,random_state=C.seed+1,n_jobs=1)
    Ftr=shape_features(Ytr);Fv=shape_features(Yv);Ft=shape_features(Yt);rfshape.fit(Ftr,Ltr)
    rawp=rfraw.predict_proba(Xt);shapep=rfshape.predict_proba(Ft)
    vrrows,vresults,vtime=execute_fits(Yv,Tv,tag='Validation')
    scale,threshold,caln=calibration(Pv,Lv,vresults)
    csvwrite('validation_predictions.csv',vrrows)
    trrows,results,timings=execute_fits(Yt,Tt,tag='Two-route three-load test')
    for j,row in enumerate(trrows):
        row['truth']=int(Lt[j]);row['raw_rf_prediction']=int(rawp[j].argmax());row['shape_rf_prediction']=int(shapep[j].argmax())
    csvwrite('test_predictions.csv',trrows)
    mainmetrics={
      'Raw-profile random forest':metrics(Lt,rawp.argmax(axis=1),rawp),
      'Morphology random forest':metrics(Lt,shapep.argmax(axis=1),shapep),
      'Physics twin two routes three loads':metrics(Lt,[r['prediction'] for r in results],[r['weights'] for r in results])}
    gates,gate=gated_metrics(Lt,results,threshold)
    uncertainty=uncertainty_table(Pt,Lt,results,scale)
    ablations={}
    for name,kwargs in [('One route three loads',{'single':True}),('Two routes one load',{'one_load':True})]:
        rr,ff,tt=execute_fits(Yt,Tt,tag=name,**kwargs)
        csvwrite(name.lower().replace(' ','_')+'.csv',rr)
        ablations[name]=metrics(Lt,[r['prediction'] for r in ff],[r['weights'] for r in ff])
    print('Main metrics',clean_json(mainmetrics),flush=True)
    # Noise sensitivity: 80 fixed held-out configurations, balanced by class.
    idx=np.r_[np.arange(0,20),np.arange(120,140),np.arange(240,260),np.arange(360,380)]
    noisestats=[];robustrows=[]
    for si,sigma in enumerate([.25,.75,1.5,3.]):
        rng=np.random.default_rng(C.seed+100+si);YS=[];TS=[]
        for j in idx:
            y,_,_,_,tc,_=optical_observation(Pt[j],rng,sigma=sigma);YS.append(y);TS.append(tc)
        rr,ff,tt=execute_fits(np.array(YS),np.array(TS),sigma=sigma,tag=f'Noise {sigma}')
        m=metrics(Lt[idx],[r['prediction'] for r in ff]);m['sigma']=sigma
        m['correct']=int(np.sum(np.array([r['prediction'] for r in ff])==Lt[idx]))
        noisestats.append(m)
        for j,r in zip(idx,rr):robustrows.append({'scenario':'noise','setting':sigma,'source_test_id':int(j),'truth':int(Lt[j]),**r})
    rng=np.random.default_rng(C.seed+200);YM=[];TM=[];PM=[]
    for j in idx:
        p={**Pt[j],'kfactors':tuple(rng.uniform(.7,1.3,2)),'gauge':float(rng.uniform(.035,.075)),'E':float(C.E*rng.uniform(.95,1.05)),'mismatch':True}
        y,_,_,_,tc,_=optical_observation(p,rng);YM.append(y);TM.append(tc);PM.append(p)
    rr,ff,tt=execute_fits(np.array(YM),np.array(TM),tag='Model mismatch')
    mismatchmetrics=metrics(Lt[idx],[r['prediction'] for r in ff]);mismatchgate,_=gated_metrics(Lt[idx],ff,threshold)
    for j,r,p in zip(idx,rr,PM):robustrows.append({'scenario':'mismatch','setting':1,'source_test_id':int(j),'truth':int(Lt[j]),**r})
    csvwrite('mismatch_configurations.csv',[{'source_test_id':int(j),'kf_A':p['kfactors'][0],'kf_B':p['kfactors'][1],'gauge_m':p['gauge'],'E_Pa':p['E'],**{k:p[k] for k in ['xc','r','xd','ld']}} for j,p in zip(idx,PM)])
    # Out-of-family shared debonding; assumption of an independent witness fails.
    YS=[];TS=[];LS=[]
    for j in range(64):
        lab=2 if j<32 else 3;p=parameter(rng,lab,'test');p['ld']=float(rng.uniform(.15,.60));p['shared']=True
        if lab==3:p['xd']=p['xc']+float(rng.uniform(-.03,.03))
        y,_,_,_,tc,_=optical_observation(p,rng);YS.append(y);TS.append(tc);LS.append(lab)
    rr,ff,tt=execute_fits(np.array(YS),np.array(TS),tag='Shared-debond challenge')
    sharedmetrics=metrics(np.array(LS),[r['prediction'] for r in ff]);sharedgate,_=gated_metrics(np.array(LS),ff,threshold)
    for j,r,l in zip(range(64),rr,LS):robustrows.append({'scenario':'shared_debond','setting':1,'source_test_id':j,'truth':l,**r})
    csvwrite('robustness_predictions.csv',robustrows)
    # Temperature omission on the same 80 physical configurations.
    YNT=[];TNT=[]
    rng=np.random.default_rng(C.seed+300)
    for j in idx:
        y,_,_,_,tc,_=optical_observation(Pt[j],rng,correct_temperature=False);YNT.append(y);TNT.append(tc)
    rr,ff,tt=execute_fits(np.array(YNT),np.array(TNT),no_temp=True,tag='No temperature reference')
    ntmetrics=metrics(Lt[idx],[r['prediction'] for r in ff]);ntgate,_=gated_metrics(Lt[idx],ff,threshold)
    csvwrite('temperature_omission.csv',[{**r,'truth':int(l)} for r,l in zip(rr,Lt[idx])])
    # Virtual sequential twin, with a Paris-law stream excluded from inverse fits.
    cycles=np.linspace(0,6e6,41);a0=.012;Cp=2e-13;stress=100.;Yedge=1.12;Kconst=Yedge*stress*np.sqrt(np.pi)
    depths=(a0**(-.5)-.5*Cp*Kconst**3*cycles)**(-2)
    rng=np.random.default_rng(C.seed+400);trace=[];previous=np.ones(4)/4
    A=np.array([[.97,.015,.015,0],[0,.98,0,.02],[0,0,.98,.02],[0,0,0,1]])
    inv=Inverse()
    traceY=[]
    for j,(N,a) in enumerate(zip(cycles,depths)):
        ld=0 if j<20 else min(.32,.06+.018*(j-20));p={'xc':3.25,'r':a/C.h,'xd':3.26 if ld else None,'ld':ld}
        y,_,_,_,tc,_=optical_observation(p,rng);inv.set_temperature(tc);res=inv.fit(y,details=True);traceY.append(y)
        accepted=res['red_chi2']<=threshold and res['confidence']>=.95
        evidence=np.asarray(res['weights']) if accepted else np.ones(4)/4
        post=(A.T@previous)*evidence;post/=post.sum();previous=post
        hp=int(post.argmax());est,se=chosen_parameters(res,h=hp)
        trace.append({'window':j,'cycles':float(N),'true_depth_mm':float(a*1000),'true_debond_mm':ld*1000,
                      'snapshot_prediction':res['prediction'],'filtered_prediction':hp,'accepted':int(accepted),'red_chi2':res['red_chi2'],
                      'estimated_depth_mm':est.get('r',0)*C.h*1000,'estimated_debond_mm':est.get('ld',0)*1000,
                      **{f'posterior_{k}':float(v) for k,v in enumerate(post)}})
    csvwrite('sequential_trace.csv',trace);np.savez_compressed(OUT/'sequential_observations.npz',strain=np.array(traceY),cycles=cycles)
    # Retain clean signatures and raw spectral shift for the illustrated example.
    profiles={}
    for lab in range(4):
        p={'xc':3.25 if lab in [1,3] else None,'r':.065 if lab in [1,3] else 0,'xd':3.27 if lab in [2,3] else None,'ld':.30 if lab in [2,3] else 0}
        profiles[str(lab)]=forward(**p,truth=True)
    np.savez_compressed(OUT/'illustrative_profiles.npz',x=XOBS,**profiles)
    summary={'status':'executed synthetic computational benchmark','config':asdict(C),'versions':{p:importlib.metadata.version(p) for p in ['numpy','scipy','matplotlib','scikit-learn','python-docx']},
             'python':sys.version,'platform':platform.platform(),'main':mainmetrics,'gated':gates,'ablations':ablations,'uncertainty':uncertainty,
             'calibration_scale':scale,'calibration_n':caln,'discrepancy_threshold':threshold,'noise':noisestats,
             'mismatch':mismatchmetrics,'mismatch_gate':mismatchgate,'shared':sharedmetrics,'shared_gate':sharedgate,
             'no_temperature':ntmetrics,'no_temperature_gate':ntgate,
             'uniform_strain_max_error_microstrain':uniform,'four_point_blind_max_difference_microstrain':blind,
             'timing_median_s':float(np.median(timings)),'timing_p95_s':float(np.quantile(timings,.95)),
             'n_train':len(Ytr),'n_val':len(Yv),'n_test':len(Yt),'runtime_s':time.perf_counter()-start,
             'sequential_accepted':int(sum(r['accepted'] for r in trace))}
    (OUT/'summary.json').write_text(json.dumps(clean_json(summary),indent=2))
    print(json.dumps(clean_json(summary),indent=2),flush=True)

if __name__=='__main__':main()
