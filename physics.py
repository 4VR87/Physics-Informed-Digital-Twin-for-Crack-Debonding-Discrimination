"""Coupled, reduced-order girder/strain-transfer/OFDR computational benchmark.

SI internally; observed strain arrays are in microstrain. No experimental data.
The truth solver uses consistent linear rod finite elements. The inverse uses
a coarser, mass-lumped finite-difference discretisation and smooth interfaces.
"""
from dataclasses import dataclass
import numpy as np
from scipy.linalg import solve_banded
from scipy.optimize import least_squares
from scipy.signal import find_peaks

@dataclass
class Config:
    L: float = 8.0
    h: float = 0.6
    b: float = 0.04
    E: float = 210e9
    Ef: float = 72e9
    rf: float = 62.5e-6
    transfer_length: float = 0.060
    gauge: float = 0.050
    pe: float = 0.22
    alpha_s: float = 12e-6
    alpha_f: float = 0.55e-6
    xi: float = 8.6e-6
    wavelength: float = 1550e-9
    force: float = 55e3
    truth_dx: float = 0.0025
    inverse_dx: float = 0.010
    spacing: float = 0.025
    sigma: float = 0.75
    rho_noise: float = 0.30
    seed: int = 20261010
    @property
    def I(self): return self.b*self.h**3/12
    @property
    def EA(self): return self.Ef*np.pi*self.rf**2
    @property
    def kb(self): return self.EA/self.transfer_length**2
    @property
    def nu0(self): return 299792458./self.wavelength

C = Config()
XOBS = np.arange(0.30, C.L-0.30+1e-8, C.spacing)
LOADS = np.array([2.,4.,6.])
CLASSES = ['Healthy','Crack','Debond','Both']

def fracture_polynomial(r):
    return .6384*r**2-1.035*r**3+3.7201*r**4-5.1773*r**5+7.553*r**6-7.3324*r**7+2.4909*r**8

def compliance(r, E=C.E):
    return 72*np.pi*fracture_polynomial(r)/(E*C.b*C.h**2)

def moment(x, loads=LOADS, forces=None):
    x=np.asarray(x)
    p=np.ones(len(loads))*C.force if forces is None else np.asarray(forces)
    # Each column is a separate diagnostic load case, not simultaneous loading.
    return np.stack([P*(C.L-s)/C.L*x-P*np.maximum(x-s,0) for s,P in zip(loads,p)],axis=-1)

def healthy_rotation(x, loads=LOADS, forces=None,E=C.E):
    x=np.asarray(x)
    p=np.ones(len(loads))*C.force if forces is None else np.asarray(forces)
    out=[]
    for s,P in zip(loads,p):
        RA=P*(C.L-s)/C.L
        q=(RA*x**2/2-P*np.maximum(x-s,0)**2/2)/(E*C.I)
        theta0=-(RA*C.L**3/6-P*(C.L-s)**3/6)/(E*C.I*C.L)
        out.append(q+theta0)
    return np.stack(out,axis=-1)

def host_displacement(x, xc=None,r=0, loads=LOADS,E=C.E,smooth=0):
    th=healthy_rotation(x,loads,E=E)
    if r>0 and xc is not None:
        jump=moment(np.asarray([xc]),loads)[0]*compliance(r,E)
        H=(np.asarray(x)>=xc).astype(float) if smooth==0 else .5*(1+np.tanh((np.asarray(x)-xc)/smooth))
        th=th+(H[:,None]-(C.L-xc)/C.L)*jump
    # Sign convention: positive sagging yields positive lower-surface strain.
    return C.h/2*th

def rod_solve(x,uh,xd=None,ld=0,kfactor=1.,truth=True,residual=0,edge=0,spatial=0,thermal=None):
    """Free axial traction at both fibre ends; positive elastic bond stiffness."""
    dx=x[1]-x[0]; n=len(x); xm=(x[:-1]+x[1:])/2
    k=C.kb*kfactor*np.ones(n-1)
    if spatial: k*=1+spatial*np.sin(2*np.pi*xm/C.L+0.4)
    if ld>0 and xd is not None:
        if edge>0:
            inside=.5*(np.tanh((xm-(xd-ld/2))/edge)-np.tanh((xm-(xd+ld/2))/edge))
        else: inside=(np.abs(xm-xd)<=ld/2).astype(float)
        k*=1-(1-residual)*inside
    diag=np.zeros(n); off=np.full(n-1,-C.EA/dx)
    diag[:-1]+=C.EA/dx; diag[1:]+=C.EA/dx
    rhs=np.zeros_like(uh)
    if truth:
        diag[:-1]+=k*dx/3; diag[1:]+=k*dx/3
        off+=k*dx/6
        # Consistent foundation mass and right-hand-side, not nodal sampling.
        rhs[:-1]+=k[:,None]*dx/6*(2*uh[:-1]+uh[1:])
        rhs[1:]+=k[:,None]*dx/6*(uh[:-1]+2*uh[1:])
    else:
        diag[:-1]+=k*dx/2; diag[1:]+=k*dx/2
        rhs[:-1]+=k[:,None]*dx/2*uh[:-1]
        rhs[1:]+=k[:,None]*dx/2*uh[1:]
    if thermal is not None:
        # EA * alpha_f * int T v' dx in the weak-form load vector.
        tm=(thermal[:-1]+thermal[1:])/2
        rhs[:-1]-=C.EA*C.alpha_f*tm
        rhs[1:]+=C.EA*C.alpha_f*tm
    ab=np.zeros((3,n)); ab[0,1:]=off; ab[1]=diag; ab[2,:-1]=off
    return solve_banded((1,1),ab,rhs,overwrite_ab=True,overwrite_b=True,check_finite=False)

def sample_strain(x,uf,gauge=C.gauge):
    # Exact gauge integral of piecewise-linear displacement.
    return np.stack([(np.interp(XOBS+gauge/2,x,uf[:,j])-np.interp(XOBS-gauge/2,x,uf[:,j]))/gauge*1e6 for j in range(uf.shape[1])])

def temperature_field(x,coeff):
    xx=np.asarray(x)/C.L
    B=np.stack([np.ones_like(xx),xx-.5,np.sin(np.pi*xx)])
    return B.T@np.asarray(coeff).T

def thermal_displacement(x,coeff):
    # Exact integral from 0 to x of the assumed reference temperature basis.
    xx=np.asarray(x); B=np.stack([xx,xx**2/(2*C.L)-xx/2,C.L/np.pi*(1-np.cos(np.pi*xx/C.L))])
    return C.alpha_s*(B.T@np.asarray(coeff).T)

def forward(xc=None,r=0,xd=None,ld=0,truth=False, kfactors=(1.,1.),gauge=C.gauge,loads=LOADS,E=C.E,mismatch=False,shared=False,temp_coeff=None):
    dx=C.truth_dx if truth else C.inverse_dx
    x=np.linspace(0,C.L,round(C.L/dx)+1)
    uh=host_displacement(x,xc,r,loads,E=E,smooth=0 if truth else .008)
    thermal=None
    if temp_coeff is not None:
        uh=uh+thermal_displacement(x,temp_coeff)
        thermal=temperature_field(x,temp_coeff)
    signals=[]
    for channel in range(2):
        loss=(channel==0 or shared)
        uf=rod_solve(x,uh,xd if loss else None,ld if loss else 0,kfactors[channel],truth=truth,
                     residual=.05 if mismatch else 0,edge=.012 if mismatch else (0 if truth else .008),spatial=.15 if mismatch else 0,thermal=thermal)
        signals.append(sample_strain(x,uf,gauge))
    return np.asarray(signals)

def ar_noise(rng,shape,sigma=C.sigma):
    z=rng.normal(size=shape); out=np.empty_like(z); out[...,0]=z[...,0]
    for j in range(1,shape[-1]):
        out[...,j]=C.rho_noise*out[...,j-1]+np.sqrt(1-C.rho_noise**2)*z[...,j]
    return sigma*out

def optical_observation(parameters,rng,temperature_amp=3.,sigma=C.sigma,correct_temperature=True,loads=LOADS):
    """OFDR spectral-shift observation in calibrated strain units.

    A load-unload difference cancels a static temperature field. The temperature
    drift during the acquisition is measured by a free reference fibre. Common
    residual reference uncertainty is retained in the observed mechanical data.
    """
    nq=len(loads)
    xx=XOBS/C.L
    coeff=rng.normal(size=(nq,3))*np.array([3.,1.,temperature_amp])
    basis=np.stack([np.ones_like(xx),xx-.5,np.sin(np.pi*xx)])
    temp=coeff@basis
    # Convert total fibre strain to spectral-shift-equivalent strain.
    beta=((C.xi+C.alpha_f)/(1-C.pe)-C.alpha_f)*1e6
    tref_error=rng.normal(size=(nq,3))*np.array([.03,.02,.015])
    tref=temp+tref_error@basis
    total=forward(**parameters,truth=True,loads=loads,temp_coeff=coeff)
    equiv=total+beta*temp[None]+ar_noise(rng,total.shape,sigma)
    raw_shift=-C.nu0*(1-C.pe)*equiv*1e-6
    recovered=-raw_shift/(C.nu0*(1-C.pe))*1e6
    healthyT=forward(truth=False,loads=loads,temp_coeff=coeff+tref_error)-forward(truth=False,loads=loads)
    if correct_temperature: recovered-=beta*tref[None]+healthyT
    return recovered,raw_shift,temp,tref,coeff+tref_error,coeff

class Inverse:
    """Constrained physical maximum-likelihood fits with BIC model weights."""
    def __init__(self,loads=LOADS,sigma=C.sigma,single=False):
        self.loads=np.asarray(loads); self.sigma=sigma; self.single=single
        self.healthy=forward(loads=self.loads)
        self.nc=1 if single else 2
        self.q=len(self.loads); self.n=len(XOBS)
        # Three profiled nuisance terms per route and load: offset, x, healthy strain.
        self.qbasis=[]
        for route in range(self.nc):
            qb=[]
            for j in range(self.q):
                B=np.stack([np.ones(self.n),(XOBS-4)/4,self.healthy[route,j]/100],axis=-1)
                W=self.whiten(B.T).T
                qb.append(np.linalg.qr(W)[0])
            self.qbasis.append(qb)
        self.neff=self.nc*self.q*(self.n-3)
        self.temp_coeff=None; self.healthyT=0

    def set_temperature(self,coeff=None):
        self.temp_coeff=coeff
        self.healthyT=0 if coeff is None else forward(loads=self.loads,temp_coeff=coeff)-self.healthy

    def whiten(self,a):
        b=np.array(a,copy=True)
        b[...,1:]=(a[...,1:]-C.rho_noise*a[...,:-1])/np.sqrt(1-C.rho_noise**2)
        return b/self.sigma

    def project(self,a):
        a=self.whiten(a[:self.nc]); out=np.empty_like(a)
        for route in range(self.nc):
            for j in range(self.q):
                B=self.qbasis[route][j]
                out[route,j]=a[route,j]-B@(B.T@a[route,j])
        return out

    def prediction(self,h,p):
        xc=r=xd=ld=None
        if h==1: xc,r=p
        elif h==2: xd,ld=p
        elif h==3: xc,r,xd,ld=p
        return forward(xc=xc,r=r or 0,xd=xd,ld=ld or 0,loads=self.loads,temp_coeff=self.temp_coeff)-self.healthyT

    def fit(self,y,details=False):
        yp=self.project(y-self.healthy)
        def res(h,p): return (yp-self.project(self.prediction(h,p)-self.healthy)).ravel()
        # Peak seeds are extracted from both load-conditioned channels.
        residual=y-self.healthy
        crsignal=residual[0 if self.single else 1].mean(axis=0)
        energy=np.sum((residual[0]-(0 if self.single else residual[1]))**2,axis=0)
        smooth_energy=np.convolve(energy,np.ones(9)/9,mode='same')
        ci=int(np.argmax(crsignal)); di=int(np.argmax(smooth_energy))
        cseed=float(np.clip(XOBS[ci],.8,7.2)); dseed=float(np.clip(XOBS[di],.8,7.2))
        # Boundary restrictions keep damaged segments clear of fibre free ends.
        fits=[]
        for h in range(4):
            if h==0:
                rr=res(0,[]); fits.append({'h':h,'p':[],'rss':float(rr@rr),'jac':None,'cost':0,'nfev':1}); continue
            if h==1:
                lo=[.8,.002]; hi=[7.2,.22]; seeds=[[cseed,.055],[cseed,.11]]
            elif h==2:
                lo=[.8,.025]; hi=[7.2,.65]; seeds=[[dseed,.12],[dseed,.35],[dseed,.55]]
            else:
                lo=[.8,.002,.8,.025]; hi=[7.2,.22,7.2,.65]
                seeds=[[cseed,.055,dseed,.15],[cseed,.11,dseed,.40],[cseed,.07,cseed,.35]]
            best=None
            for p0 in seeds:
                opt=least_squares(lambda p:res(h,p),p0,bounds=(lo,hi),x_scale='jac',max_nfev=65,
                                  diff_step=1e-3,ftol=3e-5,xtol=3e-5,gtol=1e-4)
                rss=float(opt.fun@opt.fun)
                if best is None or rss<best['rss']:
                    best={'h':h,'p':opt.x.tolist(),'rss':rss,'jac':opt.jac if details else None,
                          'cost':float(opt.cost),'nfev':int(opt.nfev)}
            fits.append(best)
        # The variance is prescribed, so -2 log L is RSS, not n log(RSS/n).
        bic=np.array([f['rss']+len(f['p'])*np.log(self.neff) for f in fits])
        weights=np.exp(-.5*np.clip(bic-bic.min(),0,1450)); weights/=weights.sum()
        pred=int(np.argmin(bic)); best=fits[pred]
        return {'prediction':pred,'weights':weights.tolist(),'bic':bic.tolist(),'fits':fits,
                'red_chi2':best['rss']/max(1,self.neff-len(best['p'])),'n_eff':self.neff,
                'confidence':float(weights[pred])}

def beam_fe(load=4.,r=.10,xc=3.25,ne=40):
    """Independent cubic Hermite beam FE with duplicated crack rotations."""
    nodes=np.unique(np.r_[np.linspace(0,C.L,ne+1),load,xc])
    n=len(nodes); crack=int(np.argmin(abs(nodes-xc)))
    extra=2*n
    K=np.zeros((extra+1,extra+1)); F=np.zeros(extra+1)
    for i,(a,b) in enumerate(zip(nodes[:-1],nodes[1:])):
        l=b-a
        ke=C.E*C.I/l**3*np.array([[12,6*l,-12,6*l],[6*l,4*l*l,-6*l,2*l*l],[-12,-6*l,12,-6*l],[6*l,2*l*l,-6*l,4*l*l]])
        dofs=[2*i,extra if i==crack else 2*i+1,2*i+2,2*i+3]
        K[np.ix_(dofs,dofs)]+=ke
    kc=1/compliance(r)
    K[np.ix_([2*crack+1,extra],[2*crack+1,extra])]+=kc*np.array([[1,-1],[-1,1]])
    F[2*np.argmin(abs(nodes-load))]=C.force
    free=np.setdiff1d(np.arange(extra+1),[0,2*n-2])
    z=np.zeros(extra+1); z[free]=np.linalg.solve(K[np.ix_(free,free)],F[free])
    return nodes,z,crack,extra

def beam_fe_rotation(x,nodes,z,crack,extra):
    # FE displacement sign is downward; host rotation is negative FE slope.
    out=[]
    for xx in x:
        i=min(np.searchsorted(nodes,xx,side='right')-1,len(nodes)-2); i=max(i,0)
        l=nodes[i+1]-nodes[i]; t=(xx-nodes[i])/l
        dofs=[2*i,extra if i==crack else 2*i+1,2*i+2,2*i+3]
        dN=np.array([(-6*t+6*t*t)/l,1-4*t+3*t*t,(6*t-6*t*t)/l,-2*t+3*t*t])
        out.append(-dN@z[dofs])
    return np.array(out)
