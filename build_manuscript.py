"""Create the research manuscript with native Word equations and measured outputs."""
from pathlib import Path
import json,csv,re,zipfile
from datetime import datetime,timezone
import numpy as np
from docx import Document
from docx.shared import Inches,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH,WD_TAB_ALIGNMENT
from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from word_math import omml
from physics import C

ROOT=Path(__file__).resolve().parent;R=ROOT/'results';F=ROOT/'figures'
DEST=ROOT.parent.parent/'output'/'Bridge_Girder_Physics_Informed_Digital_Twin.docx'
S=json.loads((R/'summary.json').read_text());B=json.loads((R/'bootstrap_summary.json').read_text())
doc=Document();sec=doc.sections[0]
sec.page_width=Inches(8.5);sec.page_height=Inches(11)
sec.top_margin=Inches(.77);sec.bottom_margin=Inches(.72);sec.left_margin=sec.right_margin=Inches(1.)
sec.header_distance=Inches(.30);sec.footer_distance=Inches(.30)
styles=doc.styles
for st in styles:
    if hasattr(st,'font'):
        st.font.color.rgb=RGBColor(0,0,0)
        if st.name not in ['Default Paragraph Font']:st.font.name='Times New Roman'
normal=styles['Normal'];normal.font.size=Pt(11)
normal.paragraph_format.line_spacing=1.08;normal.paragraph_format.space_after=Pt(6)
normal.paragraph_format.widow_control=True
for name,size in [('Title',16),('Heading 1',12),('Heading 2',11.5),('Heading 3',11)]:
    st=styles[name];st.font.size=Pt(size);st.font.color.rgb=RGBColor(0,0,0);st.font.bold=name!='Title'
    st.paragraph_format.space_before=Pt(10 if name!='Title' else 0)
    st.paragraph_format.space_after=Pt(5);st.paragraph_format.keep_with_next=True
styles['Title'].font.bold=True;styles['Title'].paragraph_format.line_spacing=1.04
for st in styles:
    for fonts in st.element.xpath('.//w:rFonts'):
        for attr in list(fonts.attrib):
            if 'theme' in attr.lower():del fonts.attrib[attr]
for border in styles['Title'].element.xpath('.//w:pBdr'):
    border.getparent().remove(border)
styles['Caption'].font.name='Times New Roman';styles['Caption'].font.size=Pt(9.5);styles['Caption'].font.color.rgb=RGBColor(0,0,0)
styles['Caption'].font.bold=False
for bold in styles['Caption'].element.xpath('.//w:bCs'):
    bold.set(qn('w:val'),'0')
styles['Caption'].paragraph_format.line_spacing=1.0;styles['Caption'].paragraph_format.space_after=Pt(8)
styles.add_style('Equation',1);styles['Equation'].font.name='Cambria Math';styles['Equation'].font.size=Pt(11)
styles['Equation'].paragraph_format.space_before=Pt(2);styles['Equation'].paragraph_format.space_after=Pt(5)
styles['Equation'].paragraph_format.line_spacing=1.05
styles.add_style('Algorithm',1);styles['Algorithm'].font.name='Consolas';styles['Algorithm'].font.size=Pt(9)
styles['Algorithm'].paragraph_format.space_after=Pt(3);styles['Algorithm'].paragraph_format.line_spacing=1.0

header=sec.header.paragraphs[0];header.alignment=WD_ALIGN_PARAGRAPH.RIGHT
run=header.add_run('Distributed optical-fibre diagnosis    Computational study');run.font.size=Pt(8.5)
footer=sec.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.CENTER
run=footer.add_run();fld=OxmlElement('w:fldSimple');fld.set(qn('w:instr'),'PAGE');run._r.addnext(fld)

EQ=[];CAPS=[];TABLES=[]
def p(text,style=None,align=None):
    para=doc.add_paragraph(style=style)
    # Author inline subscripts as editable math, not simulated subscript brackets.
    pos=0
    for match in re.finditer(r'([A-Za-zα-ωΑ-Ωℓ][′]?)₍([^₎]+)₎',text):
        para.add_run(text[pos:match.start()])
        base=match.group(1).replace('′',r'^{\prime}')
        para._p.append(omml(base+'_{'+match.group(2)+'}'))
        pos=match.end()
    para.add_run(text[pos:])
    if style is None:para.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY
    if align is not None:para.alignment=align
    return para
def h(text,level=1):return doc.add_paragraph(text,'Heading '+str(level))
def eq(source,num,continued=False):
    para=doc.add_paragraph(style='Equation');pf=para.paragraph_format
    pf.tab_stops.add_tab_stop(Inches(3.1),WD_TAB_ALIGNMENT.CENTER)
    pf.tab_stops.add_tab_stop(Inches(6.5),WD_TAB_ALIGNMENT.RIGHT)
    para.add_run('\t');para._p.append(omml(source))
    if num is not None:para.add_run('\t('+str(num)+')');EQ.append(str(num))
    if continued:pf.keep_with_next=True;pf.space_after=Pt(1)
    return para
def fig(num,name,caption,width=6.35):
    q=doc.add_paragraph();q.alignment=WD_ALIGN_PARAGRAPH.CENTER;q.paragraph_format.space_after=Pt(3);q.paragraph_format.keep_with_next=True
    rr=q.add_run();rr.add_picture(str(F/(name+'.png')),width=Inches(width))
    # Alternative text on the image as well as a numbered, searchable caption.
    rr._r.xpath('.//wp:docPr')[0].set('descr',caption)
    q=doc.add_paragraph(style='Caption');q.add_run(f'Figure {num}. ').bold=True;q.add_run(caption);CAPS.append((num,name,caption))
def table(num,title,headers,rows,widths,fontsize=9.5,leftcols=(0,)):
    cap=doc.add_paragraph(style='Caption');cap.add_run(f'Table {num}. ').bold=True;cap.add_run(title);cap.paragraph_format.keep_with_next=True
    tb=doc.add_table(rows=1,cols=len(headers));tb.alignment=WD_TABLE_ALIGNMENT.CENTER;tb.autofit=False
    for col,w in zip(tb.columns,widths):col.width=Inches(w)
    for i,txt in enumerate(headers):tb.rows[0].cells[i].text=str(txt)
    for row in rows:
        cells=tb.add_row().cells
        for i,txt in enumerate(row):cells[i].text=str(txt)
    for ri,row in enumerate(tb.rows):
        trpr=row._tr.get_or_add_trPr();no=OxmlElement('w:cantSplit');trpr.append(no)
        if ri==0:
            repeat=OxmlElement('w:tblHeader');trpr.append(repeat)
        for ci,cell in enumerate(row.cells):
            cell.width=Inches(widths[ci]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tcpr=cell._tc.get_or_add_tcPr();mar=OxmlElement('w:tcMar')
            for side,val in [('top','75'),('bottom','75'),('left','105'),('right','105')]:
                x=OxmlElement('w:'+side);x.set(qn('w:w'),val);x.set(qn('w:type'),'dxa');mar.append(x)
            tcpr.append(mar);border=OxmlElement('w:tcBorders')
            for side in ['top','left','bottom','right']:
                x=OxmlElement('w:'+side);x.set(qn('w:val'),'single');x.set(qn('w:sz'),'4');x.set(qn('w:color'),'D9D9D9');border.append(x)
            tcpr.append(border)
            if ri==0:
                sh=OxmlElement('w:shd');sh.set(qn('w:fill'),'DFE8F0');tcpr.append(sh)
            for pa in cell.paragraphs:
                pa.paragraph_format.space_after=Pt(1);pa.paragraph_format.space_before=Pt(1);pa.paragraph_format.line_spacing=1.02
                pa.alignment=WD_ALIGN_PARAGRAPH.LEFT if ci in leftcols else WD_ALIGN_PARAGRAPH.CENTER
                if ri==0:pa.paragraph_format.keep_with_next=True
                for rr in pa.runs:rr.font.size=Pt(fontsize);rr.font.bold=ri==0;rr.font.color.rgb=RGBColor(0,0,0)
    after=doc.add_paragraph();after.paragraph_format.space_after=Pt(1);after.paragraph_format.space_before=Pt(0);after.paragraph_format.line_spacing=.4
    TABLES.append((num,title,len(rows)))
    return tb
def pct(x):return f'{100*x:.2f}'

TITLE='Physics-Informed Digital Twin for Distinguishing Fatigue Cracks from Fibre Debonding in Distributed Optical-Fibre Monitoring of Bridge Girders'
p(TITLE,'Title')
p('Research article draft for author review',align=WD_ALIGN_PARAGRAPH.LEFT)
p('[Author names, affiliations, ORCID identifiers and corresponding-author details to be supplied.]',align=WD_ALIGN_PARAGRAPH.LEFT)
h('Abstract')
p('Fibre debonding changes the transfer of structural displacement to distributed optical-fibre measurements and can obscure fatigue-crack diagnosis. This study develops a physics-informed virtual digital twin that jointly identifies a structural crack and a local bond loss by comparing two independently bonded sensing routes under known diagnostic loads. The forward model couples girder equilibrium, a rotational crack compliance, a fibre shear-lag finite-element model and a finite-gauge Rayleigh spectral-shift observation model. Four constrained physical hypotheses are weighted using the Bayesian information criterion; validation-scaled parameter intervals and a residual discrepancy gate expose uncertainty. Executed Python simulations comprise 1,200 training acquisitions, 240 calibration acquisitions and 480 test acquisitions with damaged locations withheld from training. The two-route, three-load twin achieves 96.25% balanced accuracy, compared with 92.08% for a morphology-based random forest and 87.08% for a single-route twin. Conditional crack-position and crack-depth mean absolute errors are 1.28 mm and 0.29 mm. Model mismatch reduces balanced accuracy to 85.00%, while simultaneous bond loss on both routes violates the witness assumption. A uniform-moment counterexample demonstrates that substantial debonding can remain optically unobservable. A 41-window virtual fatigue stream illustrates sequential diagnosis without supplying its growth law to the inverse model. The contribution is an explicit joint-fault inference and observability benchmark; the results are synthetic and do not establish field accuracy, hardware detection limits or remaining bridge life.')
p('Keywords: distributed optical-fibre sensing; fibre debonding; fatigue crack; virtual digital twin; physics-informed inverse inference; observability; structural health monitoring.',align=WD_ALIGN_PARAGRAPH.LEFT)

h('1 Introduction')
p('Distributed optical-fibre sensing can turn a bonded fibre into a spatial record of structural deformation. Rayleigh spectral correlation is an established route to distributed strain measurement [1], but the relationship between the measured fibre strain and the host structure depends on gauge settings and mechanical transfer. Experiments with different sensor types and spatial resolutions show that large strain gradients can impair measurement quality and crack-width reconstruction [2]. For a bridge girder, an unusual optical profile therefore requires a diagnosis of the structure and of the sensing attachment itself.')
p('The distinction is mechanical. An opening crack introduces a displacement discontinuity in the host. Debonding changes the stiffness through which that displacement reaches the fibre. The fibre may bridge a debonded region and redistribute its strain without a corresponding structural crack. Conversely, a real crack can coexist with bond loss and produce a broadened or attenuated optical peak. A threshold on peak strain cannot, by itself, establish which mechanism is responsible or whether a fitted crack size is trustworthy.')
p('Strain transfer is a mature modelling subject. Ansari and Libo introduced a bond and interface transfer model [3], and Falcetelli et al. studied surface-bonded multilayer sensors and boundary conditions [4]. Bassil et al. considered imperfect bonding for concrete crack monitoring [5], while Chapeleau and Bassil developed an arbitrary-field transfer solution [6]. Zhang et al. addressed the conversion of host displacement discontinuities into fibre deformation [7]. These contributions establish the physical basis for transfer-aware sensing; the present study does not claim to originate shear-lag modelling.')
p('More recent work directly addresses inelastic interfaces and inverse reconstruction. Tan et al. combined interfacial mechanics, metaheuristic inverse analysis and OFDR experiments [8]. Lin et al. developed a fracture-energy-based crack interpretation model and reported difficulties for multiple cracks after debonding [9]. Zhao et al. combined inverse finite-element reconstruction and support vector regression for automated crack diagnosis [10]. Chen et al. integrated distributed sensing and a dynamic Bayesian network for fatigue-crack prediction [11]. These studies show that inverse analysis, machine learning and probabilistic crack tracking already exist in this field.')
p('Physics-informed bridge inference is also established. Dong et al. used intergirder physical correlations to reconstruct distributed bridge strains [12]. Andrés Arcones et al. combined experimentally calibrated finite elements, model-form uncertainty and Bayesian tendon-breakage localization, including an assessment of sensor separability [13]. A digital-twin label, a neural network or an uncertainty term is therefore insufficient as a novelty claim. The narrower question considered here is whether a coupled structural and sensing model can distinguish a crack, a bond defect and their coexistence when measurements are finite, noisy and partially inconsistent with the assumed model.')
table(1,'Position of the study within the closest reviewed primary research. Access labels describe the material actually examined.',
      ['Study','Established contribution','Focus of distinction here','Access'],[
      ['Bassil et al. [5]','Imperfect multilayer crack transfer','Joint structural and sensing-state classification','Abstract'],
      ['Tan et al. [8]','Inverse cohesive interface mechanics','Two routes and multiple diagnostic loads','Abstract'],
      ['Lin et al. [9]','Crack opening after interface debond','Witness failure and ambiguous observations','Abstract'],
      ['Zhao et al. [10]','iFEM and SVR crack inference','Explicit competing bond-loss hypothesis','Abstract'],
      ['Chen et al. [11]','OFDR and probabilistic fatigue prediction','Attachment fault distinguished from crack state','Abstract'],
      ['Dong et al. [12]','Physics-guided bridge strain reconstruction','Local crack–bond separation','Full text'],
      ['Andrés Arcones et al. [13]','Bayesian DFOS inference with model uncertainty','Joint route covariance assumptions and bond faults','Full text']],
      [.94,2.0,2.77,.79],fontsize=9,leftcols=(0,1,2))
p('Within these reviewed sources, the candidate contribution is a load-conditioned, two-route joint-fault inference benchmark that makes its failure modes explicit. The first hypothesis is that an independently bonded witness route improves separation of a structural discontinuity from bond loss on the suspect route. The second is that known load diversity improves diagnosis by changing the local host strain gradient. The third is that discrepancy checks and calibrated intervals reveal limitations that point accuracy alone conceals. These hypotheses are tested using route and load ablations, strong statistical baselines, withheld damage-location bands and out-of-family challenges. The literature search was targeted rather than exhaustive; universal priority is not claimed.')
p('All results reported below are generated by executed numerical code. The girder is an equivalent rectangular benchmark, the fatigue stream is prescribed, and no bridge measurements or commercial multiphysics runs are represented as completed experiments. The term virtual digital twin denotes a computational asset model updated by synthetic sensing streams. A deployed twin would additionally require a calibrated physical asset, interrogator quality controls and operational data.')

h('2 Coupled structural and optical model')
h('2.1 Girder idealization and sensing routes',2)
p('The benchmark is a simply supported, linearly elastic 8 m girder with an equivalent rectangular section. It represents a tractable flexural strip, rather than a detailed welded I-girder, bridge deck or vehicle–bridge interaction model. The lower sensing surface is 0.30 m from the neutral axis. Routes A and B experience the same host displacement but have separate bonds; a mechanically isolated reference fibre measures temperature drift. Route A may debond in the nominal hypothesis catalogue, while route B serves as an intact witness. Simultaneous debonding of both routes is reserved as an explicit challenge to this assumption.')
fig(1,'fig01_routing','Original schematic of the proposed bridge-girder sensing arrangement and the two different physical mechanisms. The bridge drawing is illustrative; the numerical asset is the equivalent rectangular girder defined in Table 2. Independent adhesive routes do not guarantee independent degradation in service.')
table(2,'Chosen inputs for the synthetic benchmark. Values are study assumptions, not measured properties of a particular bridge or interrogator.',
      ['Quantity','Symbol or definition','Value'],[
      ['Span and rectangular section','L, b, h','8.00 m; 0.040 m; 0.600 m'],
      ['Steel elastic modulus','E','210 GPa'],
      ['Second moment of area','I = bh³/12','7.20 × 10⁻⁴ m⁴'],
      ['Fibre modulus and radius','Fibre E; fibre radius','72 GPa; 62.5 µm'],
      ['Fibre axial rigidity','Fibre EA','883.57 N'],
      ['Nominal transfer length','ℓₜ = √(fibre EA / k₀)','60 mm'],
      ['Effective bond foundation stiffness','k₀','2.454 × 10⁵ N m⁻²'],
      ['Independent diagnostic point loads','P; s','55 kN; 2, 4 and 6 m'],
      ['Gauge length and sample pitch','Lɢ, Δxₒ','50 mm; 25 mm'],
      ['Observed interval and samples per route','x; Nₓ','0.30–7.70 m; 297'],
      ['Optical wavelength and photoelastic factor','λ₀, pₑ','1550 nm; 0.22'],
      ['Steel and silica thermal expansion','Steel α; silica α','12.0 × 10⁻⁶; 0.55 × 10⁻⁶ K⁻¹'],
      ['Silica thermo-optic coefficient','ξ','8.6 × 10⁻⁶ K⁻¹'],
      ['Strain noise and adjacent correlation','σ, ρₙ','0.75 µε; 0.30'],
      ['Reference-temperature coefficient noise','constant, linear, sine basis','0.030, 0.020, 0.015 K'],
      ['Truth and inverse fibre meshes','Δxₜ, Δxᵢ','2.5 mm; 10 mm']],
      [2.6,2.15,1.75],fontsize=9.5,leftcols=(0,1,2))
p('Subscripts f in the equations denote the fibre; the table uses the corresponding fibre quantities. The diagnostic loads are separate quasi-static load cases, not three simultaneous forces. Their positions and magnitudes are known to the inverse model. Global stiffness, lever arm and nominal transfer length are fixed chosen inputs. Their calibration from healthy bridge data is outside the present experiment.')

h('2.2 Rotational crack surrogate',2)
p('For the intact Euler–Bernoulli girder, transverse equilibrium and the bending moment for load case q are written as follows. Positive moment denotes sagging; the coordinate runs from the left support to the right support. The brackets in Eq. (2) denote the positive part of their argument.')
eq(r'EI\,w_q^{(4)}(x)=P_q\delta(x-s_q),\quad w_q(0)=w_q(L)=0',1)
eq(r'M_q(x)=\frac{P_q(L-s_q)}{L}x-P_q\langle x-s_q\rangle_+',2)
p('The end moments are zero. An open edge crack at position x₍c₎ is represented by continuous transverse displacement and a rotational jump. The standard rotational-spring compliance used in cracked-beam studies [14] supplies a depth-dependent, monotone surrogate within the shallow-crack range considered here.')
eq(r'[w_q]_{x_c}=0,\quad [\theta_q]_{x_c}=C_\theta(r)M_q(x_c),\quad r=\frac{a}{h}',3)
eq(r'C_\theta(r)=\frac{72\pi}{Ebh^2}f(r)',4)
eq(r'f(r)=0.6384r^2-1.035r^3+3.7201r^4-5.1773r^5',None,continued=True)
eq(r'\qquad +7.553r^6-7.3324r^7+2.4909r^8',5)
p('Here a is the equivalent open-crack depth, r is its section-depth ratio, and compliance has units of inverse moment. This one-dimensional law is not a calibrated representation of a weld toe, a three-dimensional crack front or crack closure. The inferred depth must therefore be interpreted as an equivalent depth under the benchmark model. The physical origin of a crack cannot be established as fatigue from a single strain snapshot; fatigue is imposed only in the chronological stream.')
p('The intact rotation follows by integration of the moment. Its integration constant is determined by the two support displacements, yielding the closed solution in Eq. (6). The cracked rotation in Eq. (7) adds the local jump and the support-compatible global correction. H is the Heaviside function.')
eq(r'\theta_{h,q}(x)=\theta_{0,q}+\frac{1}{EI}\int_0^x{M_q(s)\,ds}',None,continued=True)
eq(r'\theta_{0,q}=-\frac{1}{LEI}\int_0^L{(L-s)M_q(s)\,ds}',6)
eq(r'\theta_q(x)=\theta_{h,q}(x)+C_\theta(r)M_q(x_c)\left[H(x-x_c)-\frac{L-x_c}{L}\right]',7)
p('The sign of host displacement is chosen so that positive sagging gives positive strain at the lower surface. Thermal expansion is added at the displacement level, rather than counted again as an optical strain.')
eq(r'u_{h,q}(x)=\frac{h}{2}\theta_q(x)+\alpha_s\int_0^x{\Delta T_q(s)\,ds}',8)

h('2.3 Fibre transfer and debonding',2)
p('Each fibre route is modelled as an axial elastic rod connected to the host by a distributed shear foundation. Effective bond stiffness k₍b₎ is force per unit fibre length per unit relative displacement and has units N m⁻². It combines the coating and adhesive transfer into one effective parameter; it is not simply the adhesive shear modulus. Fibre thermal strain is included in the axial stress. Equilibrium and free-traction end conditions are')
eq(r'-\frac{d}{dx}\left[E_fA_f\left(u_{f,q}^{\prime}-\alpha_f\Delta T_q\right)\right]+k_b(x)(u_{f,q}-u_{h,q})=0',9)
p('At each fibre end, the axial force E₍f₎A₍f₎(u′₍f₎ − α₍f₎ΔT) is zero. A local bond defect occupies an interval D centred at x₍d₎ with length ℓ₍d₎. Its residual stiffness fraction is δ₍b₎; the nominal debond is traction-free with δ₍b₎ = 0. The transfer length outside that interval is ℓ₍t₎.')
eq(r'k_b(x)=k_0\left[1-(1-\delta_b)\chi_D(x)\right],\quad \ell_t=\sqrt{\frac{E_fA_f}{k_0}}',10)
p('The truth solver uses consistent two-node rod finite elements. For every test function v, the weak form is Eq. (11). The element rod term uses E₍f₎A₍f₎/Δx times the usual two-node difference matrix; the foundation term uses k₍b₎Δx/6 times the consistent matrix with diagonal 2 and off-diagonal 1. The load vector includes the host displacement and the silica thermal eigenstrain.')
eq(r'\int_0^L{E_fA_f u_{f,q}^{\prime}v^{\prime}\,dx}+\int_0^L{k_bu_{f,q}v\,dx}',None,continued=True)
eq(r'=\int_0^L{k_bu_{h,q}v\,dx}+\int_0^L{E_fA_f\alpha_f\Delta T_q v^{\prime}\,dx}',11)
p('The inverse model deliberately uses a coarser, mass-lumped discretization of the same equilibrium law. Crack steps and debond boundaries are smoothed with a hyperbolic tangent width of 8 mm, while the nominal truth model uses sharp boundaries. Thus numerical inversion is not performed with exactly the same discretization that generates the data. Both models still share the same reduced physical assumptions; agreement between them is numerical verification, not independent physical validation.')

h('2.4 Finite-gauge optical observation and temperature',2)
p('The observed strain is the average axial strain over a virtual gauge. For a piecewise-linear displacement solution, this average is evaluated directly from the two gauge-end displacements, avoiding numerical differentiation at a crack. The sample pitch and gauge length are distinct quantities: the 25 mm samples overlap the 50 mm gauge.')
eq(r'\bar{\epsilon}_{f,q}(x)=\frac{u_{f,q}(x+L_g/2)-u_{f,q}(x-L_g/2)}{L_g}',12)
p('A linearized Rayleigh spectral-shift model expresses the observation in terms of mechanical fibre strain and temperature. The relative frequency shift is defined with a negative sign for tensile mechanical strain. The base optical frequency is ν₀ = c/λ₀; p₍e₎ is the effective photoelastic factor and ξ is the silica thermo-optic coefficient.')
eq(r'\frac{\Delta\nu_q}{\nu_0}=-\left[(1-p_e)(\bar{\epsilon}_{f,q}-\alpha_f\Delta T_q)+(\xi+\alpha_f)\Delta T_q\right]',13)
p('Because Eq. (12) includes total axial strain, the temperature coefficient used when recovering that strain is β₍T₎ in Eq. (14). The reference estimate is then used in the same fibre-transfer model to subtract the predicted healthy thermal response. This leaves a compensated profile y that contains mechanical damage, the change in thermal transfer caused by the damaged bond, and reference uncertainty. Uniform silica expansion is not counted twice. The temperature field is slowly varying compared with the gauge, and its optical coefficient is evaluated at the gauge centre.')
eq(r'\beta_T=\frac{\xi+\alpha_f}{1-p_e}-\alpha_f,\quad y_q=-\frac{\Delta\nu_q}{\nu_0(1-p_e)}-\beta_T\hat{T}_q-\epsilon_{T,h,q}(\hat{T}_q)',14)
p('The thermal field is a sum of a constant, a linear term in x/L − 1/2 and a sine term sin(πx/L). Independent coefficients for each diagnostic acquisition have standard deviations 3, 1 and 3 K. The free reference measures those coefficients with the uncertainties in Table 2. The full thermal host displacement and fibre eigenstrain are solved before optical conversion. The strain-equivalent bonded temperature coefficient is approximately 23.18 µε K⁻¹ in a uniform interior region. This value follows from the selected material coefficients; it is not an experimentally calibrated compensation coefficient.')
p('The observation model computes spectral shifts from the mechanical solution; it does not synthesize Rayleigh scatter interferograms, laser phase noise, detector shot noise or interrogator dropouts. The prescribed 0.75 µε noise is therefore a conditional input to the benchmark, not a demonstrated hardware precision or detection limit. The optical strain mapping in Eq. (13) gives a mechanical shift magnitude of approximately 0.151 GHz per microstrain at the selected wavelength.')

h('3 Physics-informed inverse diagnosis and virtual twin')
h('3.1 Competing damage hypotheses',2)
p('The inverse problem explicitly separates the structural state from the sensing-attachment state. The four hypotheses are defined in Table 3. The unknown crack and debond centres need not coincide. A crack is constrained to have positive compliance; a debond is constrained to have positive length. The nominal catalogue contains one crack and one debonded interval on route A. It does not contain several cracks, fibre rupture, plasticity or a second debond on the witness route.')
table(3,'Nominal physical hypothesis catalogue and parameter bounds used in every inverse fit.',
      ['State','Physical state','Fitted parameters','Bounds'],[
      ['H₀','Intact girder and bonds','None','Fixed nominal inputs'],
      ['Hc','Open structural crack','Crack centre, depth ratio','0.8–7.2 m; 0.002–0.220'],
      ['Hd','Route A bond loss','Debond centre, length','0.8–7.2 m; 0.025–0.650 m'],
      ['Hcd','Crack and route A bond loss','Both parameter pairs','As above; centres independent']],
      [.70,1.85,1.90,2.05],leftcols=(1,2,3))
p('The forward prediction for each hypothesis includes the reference-temperature field and subtracts the same predicted healthy thermal response used in Eq. (14). This is necessary because the damaged bond changes thermal as well as mechanical strain transfer. Physical information enters through the coupled equilibrium model and parameter constraints. No neural network is trained to solve the governing equations, and the method is not presented as a PINN.')
fig(2,'fig02_framework','Executed computational framework. Synthetic optical observations are compensated and compared with four physical models. Evidence and residual checks control virtual-twin state updates. Sensitivity comparisons assess the selected loads and routes; adaptive physical load control was not implemented.')

h('3.2 Correlated observation residuals and model fitting',2)
p('Within each route and diagnostic load, the prescribed observation noise follows a stationary first-order autoregressive spatial covariance. The correlation parameter describes adjacent sampled gauges, not independent spatial experiments. W is a whitening operator for this covariance. For the stated 297 samples, whitening uses the first residual divided by σ and successive residual innovations divided by σ√(1 − ρ₍n₎²).')
eq(r'\Sigma_{ij}=\sigma^2\rho_n^{|i-j|},\quad W\Sigma W^T=I',15)
p('Three nuisance modes are profiled separately for each route and load: a constant offset, a linear spatial drift and the corresponding healthy mechanical strain profile. Their whitened columns are orthonormalized as Q. This removes broad systematic differences without fitting local crack and debond signatures with an unconstrained flexible residual. The projection P⊥ and profiled residual are')
eq(r'P_\perp=I-QQ^T,\quad e_h(\vartheta)=P_\perp W\left[y-F_h(\vartheta,\hat{T})\right]',16)
p('The reference-coefficient errors also induce smooth, shared noise across routes. The likelihood does not claim to model the full joint covariance of those errors: constant and linear terms are largely profiled, while the remaining effect is included in the synthetic validation and interval calibration. A full cross-route thermal covariance model is a necessary extension for calibrated posterior probabilities on a physical asset.')
eq(r'\hat{\vartheta}_h=\argmin_{\vartheta\in\Omega_h}\left\|e_h(\vartheta)\right\|^2,\quad R_h=\left\|e_h(\hat{\vartheta}_h)\right\|^2',17)
p('Bounded nonlinear least squares solves Eq. (17). Peak locations on the witness profile seed the crack, while load-conditioned difference energy seeds the bond defect. Crack-only fits use two initial depths, debond fits use three initial lengths, and joint fits use three paired initializations. All initializations, bounds, tolerances and the 65-function-evaluation limit are retained in the code. Multistart fitting reduces local-minimum dependence but does not establish global optimality.')
p('The Bayesian information criterion [15] penalizes the additional physical parameters. The noise variance is prescribed, so the residual term is R₍h₎, rather than n log(R₍h₎/n). There are 1,764 whitened residual coordinates after nuisance projection in the full two-route, three-load problem. Parameter counts are 0, 2, 2 and 4 for the four hypotheses. Terms common to all models are omitted.')
eq(r'\mathrm{BIC}_h=R_h+d_h\ln(n_{\mathrm{res}}),\quad w_h=\frac{\exp[-(\mathrm{BIC}_h-\mathrm{BIC}_{\min})/2]}{\sum_j{\exp[-(\mathrm{BIC}_j-\mathrm{BIC}_{\min})/2]}}',18)
p('These normalized BIC weights approximate model evidence. They are not exact Bayesian posterior probabilities and are not assumed to be calibrated confidence scores under arbitrary model mismatch. The class estimate minimizes BIC. A separate evidence and discrepancy gate accepts the snapshot only when the winning weight is at least 0.95 and the reduced residual statistic is below a validation-derived threshold.')
eq(r'z_h=\frac{R_h}{n_{\mathrm{res}}-d_h},\quad G=\chi\left(w_{h^*}\ge0.95\right)\chi\left(z_{h^*}\le\tau\right)',19)
p(f'The residual threshold is τ = {S["discrepancy_threshold"]:.4f}, the finite-sample 99th-percentile order statistic of the 240 calibration fits. This gate checks consistency with the nominal model catalogue. It cannot certify that a healthy-looking fibre has a sound attachment, and it can accept an incorrect model when distinct mechanisms produce sufficiently similar observations.')

h('3.3 Calibrated parameter intervals and local sensitivity',2)
p('For a correctly selected damage hypothesis, a local covariance approximation uses the Jacobian of the profiled, whitened prediction. The Moore–Penrose inverse is used because ill-conditioned directions are relevant to this problem. The result is a local conditional approximation, not a globally sampled posterior or a guarantee under parameter bounds.')
eq(r'J_h=P_\perp W\frac{\partial F_h}{\partial\vartheta},\quad V_h\approx(J_h^T J_h)^+',20)
p('The uncalibrated linearized intervals use 1.96 standard errors. To account for the observed numerical and reference-model discrepancy, a separate scale κ₍j₎ is obtained from the upper 95th-percentile order statistic of the absolute standardized errors on correctly classified calibration acquisitions. It is bounded below by 1.96. The test set is not used to choose these scales. The resulting intervals are')
eq(r'\mathcal{I}_j=\left[\hat{\vartheta}_j-\kappa_j\sqrt{V_{jj}},\ \hat{\vartheta}_j+\kappa_j\sqrt{V_{jj}}\right]',21)
p('Intervals are reported conditional on correct hypothesis selection. They are not simultaneous intervals, and their nominal calibration does not transfer automatically to a different geometry, attachment system or noise law. The local bands are displayed without truncation to physical bounds; the fitted estimates themselves satisfy Table 3. Coverage after a wrong class decision and unconditional detection performance are reported separately through the confusion matrix and gate counts.')
p('A sensitivity audit evaluates whether crack and bond parameters produce distinguishable optical changes. The Jacobian columns are scaled by the design increments 0.10 m for each centre, 0.02 for crack-depth ratio and 0.10 m for debond length. The singular-value ratio η is invariant to an overall signal gain but remains conditional on these chosen parameter scales.')
eq(r'J_s=J_hD,\quad D=\operatorname{diag}(0.10,0.02,0.10,0.10),\quad \eta=\frac{\sigma_{\min}(J_s)}{\sigma_{\max}(J_s)}',22)
p('The units of D correspond to the parameter units above. A small ratio indicates a direction that can change the parameters substantially while changing the profiles only weakly. This audit guides interpretation of parameter estimates. It is not used as an undisclosed test-set filter, and the manuscript does not claim that the residual gate is a complete identifiability test.')

h('3.4 Sequential state update and algorithm',2)
p('The virtual twin receives a chronological sequence of acquisition windows. A four-state Markov transition model permits crack initiation, bond loss and their coexistence, but forbids disappearance of an existing crack or bond defect during the unrepaired stream. The transition rows, in the order H₀, Hc, Hd, Hcd, are (0.970, 0.015, 0.015, 0), (0, 0.980, 0, 0.020), (0, 0, 0.980, 0.020) and (0, 0, 0, 1). The initial state weights are uniform. These are chosen diagnostic transition assumptions, not estimated bridge failure probabilities.')
eq(r'\pi_k(h)\propto\tilde{w}_{h,k}\sum_g{A_{gh}\pi_{k-1}(g)},\quad \sum_h{\pi_k(h)}=1',23)
p('For accepted snapshots, the evidence in Eq. (23) is the BIC weight. For rejected snapshots, it is replaced by a uniform vector so that untrusted measurements do not impose a new state likelihood. Parameters displayed in the stream are current fitted parameters conditioned on the most likely filtered state; their values at rejected windows remain diagnostically unconfirmed. The state filter updates class evidence, not a fully Bayesian continuous crack-growth posterior.')
alg=doc.add_paragraph(style='Caption');alg.add_run('Algorithm 1. ').bold=True;alg.add_run('Physical joint diagnosis and sequential virtual-twin update');alg.paragraph_format.keep_with_next=True
algorithm=[
'Input  Profiles from routes A and B, known loads, reference T,',
'       fixed physical inputs, covariance, calibration scales and τ.',
'01     Solve the healthy thermal response using reference T.',
'02     Convert optical shifts to compensated strain with Eq. (14).',
'03     Whiten each route/load and profile its three nuisance modes.',
'04     Seed crack position from route B and bond position from',
'       the load-conditioned route-difference energy.',
'05     For h in {healthy, crack, debond, both}:',
'       fit all prescribed starts under the bounds in Table 3;',
'       retain the fit with the smallest whitened residual norm.',
'06     Compute BIC and normalized model weights with Eq. (18).',
'07     Evaluate the evidence/discrepancy gate with Eq. (19).',
'08     Calculate local covariance and validation-scaled intervals.',
'09     Audit scaled Jacobian singular values for damage parameters.',
'10     If G = 1, update the state using the BIC evidence;',
'       otherwise use uniform evidence and flag the snapshot.',
'11     Record the state, current conditional fit, intervals,',
'       residual statistic and ambiguity flag for the virtual asset.',
'Output Joint-fault state and its stated domain of diagnostic support.'
]
for i,line in enumerate(algorithm):
    q=p(line,'Algorithm');q.paragraph_format.keep_with_next=i<len(algorithm)-1

h('4 Simulation protocol and evaluation')
h('4.1 Data generation and spatial split',2)
p('The main experiment contains 1,920 acquisition windows: 1,200 for the statistical baselines, 240 for discrepancy and interval calibration, and 480 for final testing. Each split contains equal numbers of healthy, crack-only, debond-only and joint-fault windows. Each window supplies two routes, three separate loads and 297 spatial samples, giving 1,782 observed strain values. Healthy windows share the same nominal asset and vary temperature and observation noise; they are not 480 different bridge geometries. Damaged windows additionally vary the physical fault parameters.')
p('Damage centres lie between 0.8 and 7.2 m. This interval is divided into 32 bands of width 0.20 m. Bands with index modulo four equal to three are reserved for the test set, while the other bands supply training and calibration locations. Centres are sampled 15–185 mm inside the selected band to avoid its boundary. In 55% of joint-fault windows, the two centres are drawn close together within the same eligible band; the remaining centres are drawn independently. Complete acquisition windows are split together. Spatial samples from a window are never distributed across training and test sets.')
p('Crack-depth ratios are sampled uniformly from 0.012 to 0.160, corresponding to equivalent depths of 7.2–96.0 mm. Debond lengths are sampled uniformly from 40 to 600 mm. These distributions define a balanced diagnostic benchmark rather than the prevalence of damage on actual bridges. The code fixes the base random seed at 20261010 and uses separate streams for data splits and challenges. The generated observations and numerical outputs are retained for reproducibility.')
table(4,'Executed acquisition counts and the purpose of each synthetic experiment.',
      ['Experiment','n','Allocation','Purpose'],[
      ['Training','1,200','300 per class','Fit statistical classifiers'],
      ['Calibration','240','60 per class','Choose interval scales and residual gate'],
      ['Final spatial test','480','120 per class','Withheld location bands'],
      ['Route and load ablations','480 each','Same test windows','Isolate information from routes and loads'],
      ['Noise challenge','320','80 at each of four noise levels','Repeat fixed test configurations'],
      ['Model mismatch','80','20 per class','Change stiffness, gauge and bond law'],
      ['Shared-debond challenge','64','32 bond-only; 32 crack + bond','Violate witness assumption'],
      ['Temperature omission','80','20 per class','Remove reference compensation'],
      ['Virtual fatigue stream','41','Chronological windows','Sequential state updating']],
      [2.0,.67,1.65,2.18],leftcols=(0,2,3))

h('4.2 Statistical baselines and evaluation metrics',2)
p('Two random-forest baselines [16] use the same compensated observation windows. The raw-profile forest receives the flattened whitened, nuisance-projected residuals. It has 400 trees, a minimum leaf size of two and square-root feature sampling. The stronger morphology forest uses 120 statistical features: maximum, minimum, standard deviation, upper and lower quantiles, mean absolute value, maximum adjacent change, mean squared adjacent change, skewness and kurtosis. These are extracted from healthy-reference-subtracted, mean-centred profiles for each load on both routes, their mean and their difference. This feature extraction uses the nominal healthy forward profile as a reference; classification does not fit damage-specific physical equations. The forest uses 400 trees, a minimum leaf size of two and a feature fraction of 0.6. Both configurations are fixed before test scoring; the code records their seeds.')
p('The morphology baseline is included to avoid treating a position-sensitive raw-profile classifier as the only competitor. Comparisons with these baselines do not establish superiority over all neural architectures, graph models or Bayesian inference methods. The physical method does not learn from the training windows; the separate calibration set is used for its discrepancy gate and intervals. For the ablations, one route means route A only, and one load means the 55 kN load at 4 m. The same model bounds and fitting rules are retained.')
eq(r'\mathrm{BA}=\frac{1}{4}\sum_{h=0}^3{\frac{\mathrm{TP}_h}{\mathrm{TP}_h+\mathrm{FN}_h}},\quad F_{1,h}=\frac{2\mathrm{TP}_h}{2\mathrm{TP}_h+\mathrm{FP}_h+\mathrm{FN}_h}',24)
p('Balanced accuracy is the average recall across the four states; macro F1 is the average of their F1 values. The healthy false-alarm fraction is the number of nonhealthy predictions divided by the 120 healthy test windows. A multiclass Brier score averages the squared difference between the four predicted weights and the one-hot true state, without division by four. Gate coverage is the accepted fraction and selective accuracy is accuracy among accepted windows. Incorrect accepted windows are also counted explicitly.')
eq(r'\mathrm{MAE}_j=\frac{1}{n_j}\sum_i{|\hat{\vartheta}_{ij}-\vartheta_{ij}|},\quad \mathrm{RMSE}_j=\sqrt{\frac{1}{n_j}\sum_i{(\hat{\vartheta}_{ij}-\vartheta_{ij})^2}}',25)
p('Parameter errors and interval coverage are conditional on correct class selection, with their denominators reported. Case-stratified bootstrap resampling uses 2,000 replicates and preserves the class counts. The comparison with the morphology baseline uses paired resampling of the same test windows. These intervals describe finite-sample benchmark variability for the fitted algorithms. They do not include uncertainty from retraining all algorithms, selecting another bridge or changing the fault prevalence.')

h('4.3 Mechanism signatures and numerical checks',2)
p('Figures 3 and 4 show an illustrative synthetic case with a 39 mm equivalent crack at 3.25 m and a 300 mm debond centred at 3.27 m. Profiles are shown for the load at 4 m. The crack signature appears on both routes, while bond loss changes route A. A fibre spanning the debonded interval remains continuous and carries axial force: local bond loss does not force its strain to zero. This detail is essential for interpreting distributed measurements.')
fig(3,'fig03_signatures','Synthetic finite-gauge profiles for healthy, crack-only, debond-only and joint states. Crack depth is 39 mm, crack position is 3.25 m, and the debond is 300 mm long at 3.27 m. Route B has an intact bond. These are calculated profiles, not OFDR measurements.')
p('The common residual highlights structural information shared between the two routes; the difference isolates changes in their attachments. The joint state also changes the difference around the crack because the cracked host displacement is transferred through different bonds. Thus a rule based only on the sign of a strain peak would discard important information. The inverse model uses the full load-conditioned profiles, rather than assuming exact separation of common and differential components.')
fig(4,'fig04_common_difference','Calculated common and differential residuals after subtracting the healthy profile. The secondary axis is the mechanical Rayleigh spectral-shift mapping from Eq. (13), with temperature removed for illustration. It is not an independently simulated optical receiver output.')
p('Three verification checks precede statistical diagnosis. First, an independently assembled cubic Hermite beam with duplicated rotations at the crack is compared with Eq. (7). Second, the consistent fibre-element solution is refined from 20 to 2.5 mm against a 1.25 mm reference. Third, a uniform host-strain case is checked in the fibre interior. The supplied mesh table records relative profile errors; it does not replace convergence studies of a three-dimensional cracked bridge model.')

h('4.4 Mismatch challenges and fatigue stream',2)
p('The model-mismatch experiment changes both route bond stiffnesses independently by ±30%, effective steel modulus by ±5%, and actual gauge length to 35–75 mm. The truth bond retains 5% of nominal stiffness in the defect, has 12 mm smooth edges and a 15% sinusoidal stiffness variation outside the defect. The inverse still assumes its fixed nominal inputs and traction-free debond. This intentionally combines several modelling departures; it does not identify the isolated effect of each source. The 80 challenge configurations are a balanced subset of the held-out physical states.')
p('The shared-debond challenge imposes an identical bond-loss interval on both routes, with lengths of 150–600 mm. Half of its 64 windows contain a crack near that interval. Every window lies outside the nominal witness-intact catalogue, even if a coarse Hcd class label happens to match. The temperature-omission experiment instead feeds uncorrected spectral-shift-equivalent profiles to the nominal inverse on 80 balanced windows. These challenges test the ability to flag inconsistent observations; neither provides independent physical validation.')
p('For the chronological experiment, a prescribed open-crack fatigue history is generated with a Paris-type law [17]. The selected material constant is an illustrative input, not a measured fatigue property. Stress intensity uses a constant small-edge-crack factor 1.12, a local cyclic stress range of 100 MPa and exponent three. Units of the Paris constant correspond to metres per cycle when stress intensity is expressed in MPa√m.')
eq(r'\frac{da}{dN}=C_P\left(Y_e\Delta\sigma\sqrt{\pi a}\right)^3,\quad C_P=2\times10^{-13},\quad Y_e=1.12',26)
eq(r'a(N)=\left[a_0^{-1/2}-\frac{C_P(Y_e\Delta\sigma\sqrt{\pi})^3}{2}N\right]^{-2}',27)
p('The initial depth is 12 mm and the 41 acquisition windows span 0–6 million prescribed cycles. The ratio remains below 0.085. A route A debond first appears at window 20, grows from 60 mm and reaches 320 mm. The nominal three diagnostic loads probe each frozen damage state; they are separate from the assumed fatigue cycling stress. The crack-growth equation and its material constant are never supplied to the snapshot inverse fits. The chronological stream tests state diagnosis, not fatigue-life prediction.')
p('The study was executed in Python using NumPy 2.3.5, SciPy 1.17.0 [18] and scikit-learn 1.8.0 [19]. The reproducibility package contains the complete forward and inverse code, seeds, configuration CSV files, generated observation arrays, prediction tables, figures and execution log. Computational results are Python outputs; no COMSOL, ABAQUS or MATLAB execution is claimed.')

h('5 Results and discussion')
h('5.1 Numerical verification',2)
p('The independent Hermite beam and analytical rotations agree to relative L2 errors between 2.06 × 10⁻¹¹ and 3.41 × 10⁻¹⁰ for the selected meshes. Since load and crack locations are inserted as element nodes, the piecewise cubic beam solution is represented essentially exactly; the remaining variation is floating-point conditioning, rather than a monotone beam-convergence trend. The consistent fibre model does show decreasing error under mesh refinement. Its chosen 2.5 mm truth mesh differs from the 1.25 mm reference by 0.02267% in the illustrated six-profile norm.')
table(5,'Executed numerical verification for the illustrated joint-fault state. Fibre errors are normalized by the full profile norm, including healthy strain.',
      ['Check','Discretization','Relative L2 error'],[
      ['Hermite beam versus analytical rotation','10 nominal beam elements','2.06 × 10⁻¹¹'],
      ['Hermite beam versus analytical rotation','40 nominal beam elements','2.09 × 10⁻¹¹'],
      ['Consistent fibre FE versus 1.25 mm mesh','20 mm elements','0.26639%'],
      ['Consistent fibre FE versus 1.25 mm mesh','10 mm elements','0.14888%'],
      ['Consistent fibre FE versus 1.25 mm mesh','5 mm elements','0.06729%'],
      ['Consistent fibre FE versus 1.25 mm mesh','2.5 mm elements','0.02267%'],
      ['Inverse discretization versus reference','10 mm; smoothed interfaces','0.04295%']],
      [2.9,2.0,1.6],leftcols=(0,1))
fig(5,'fig05_convergence','Executed mesh refinement of the consistent fibre-transfer model. Errors use the illustrated full profiles and a 1.25 mm reference; the line for the inverse model includes discretization and interface smoothing differences. This is a numerical verification result.')
mantissa,exponent=f'{S["uniform_strain_max_error_microstrain"]:.2e}'.split('e')
exponent=str(int(exponent)).translate(str.maketrans('0123456789-','⁰¹²³⁴⁵⁶⁷⁸⁹⁻'))
p(f'The uniform-strain interior check has a maximum error of {mantissa} × 10{exponent} µε away from the free-end transfer zones. Together these checks support the numerical implementation within its reduced model. They do not demonstrate that the selected crack compliance, thermal coefficients or effective bond stiffness reproduce a real girder attachment.')

h('5.2 Joint classification and information ablations',2)
phys=S['main']['Physics twin two routes three loads'];morph=S['main']['Morphology random forest'];delta=B['paired_difference_physics_minus_morphology']
p('The physical twin correctly classifies 462 of 480 held-out windows, giving 96.25% balanced accuracy and 96.26% macro F1. The morphology forest correctly classifies 442 windows, giving 92.08% balanced accuracy. The paired bootstrap difference is 4.17 percentage points, with a 95% benchmark interval of 2.29–6.25 percentage points. This comparison is conditional on the selected spatial split, generators and fitted baseline; it is not an estimate of a field improvement.')
perf=[]
for name,m in S['main'].items():
    lo,hi=B[name]['balanced_accuracy_ci'];perf.append([{'Raw-profile random forest':'Profile RF','Morphology random forest':'Morphology RF','Physics twin two routes three loads':'Physical twin'}[name],f'{pct(m["balanced_accuracy"])} [{pct(lo)}, {pct(hi)}]',pct(m['macro_f1']),pct(m['healthy_false_alarm']),f'{m["multiclass_brier"]:.4f}'])
for name,m in S['ablations'].items():perf.append([name,pct(m['balanced_accuracy']),pct(m['macro_f1']),pct(m['healthy_false_alarm']),f'{m["multiclass_brier"]:.4f}'])
table(6,'Four-state performance on the 480-window synthetic spatial test. Brackets are 95% stratified-bootstrap intervals. Percentages are shown to two decimal places.',
      ['Method','Balanced accuracy (%)','Macro F1 (%)','Healthy false alarm (%)','Brier score'],perf,[1.87,1.59,1.0,1.20,.84],leftcols=(0,))
fig(6,'fig06_confusion','Executed synthetic test confusion matrices. Rows are the true states and columns are predictions; each true state contains 120 windows. The morphology forest is the stronger statistical baseline. The physical twin uses both routes and all three known loads.')
p('The raw-profile forest obtains 51.25% balanced accuracy. Its poor performance is consistent with position-dependent features facing withheld location bands; it should not be interpreted as evidence that all data-driven methods fail. In contrast, the morphology baseline is insensitive to absolute peak position and performs substantially better. Including this stronger comparator limits the extent to which apparent physical-model gains are explained by a weak statistical baseline.')
p('The two-route twin recalls 119/120 healthy, 116/120 crack-only, 113/120 debond-only and 114/120 joint windows. There is one healthy false alarm, or 0.83%. The balanced test prior does not reflect bridge damage prevalence. Consequently, neither positive predictive value in service nor a maintenance alarm rate can be inferred directly from these proportions.')
p('Removing the witness route reduces balanced accuracy to 87.08%. The strongest loss occurs in the joint state: only 67 of 120 joint windows are classified correctly, and 45 are interpreted as crack-only. This is direct evidence that the second route helps expose bond loss that alters an otherwise plausible crack signature. With both routes but only the central load, balanced accuracy is 94.38%. The modest overall improvement from the extra two loads does not remove the need for load diversity in specific blind regions.')
fig(7,'fig07_comparison','Synthetic benchmark accuracy for statistical comparators and physical information ablations. Error bars are 95% case-stratified bootstrap intervals. All ablations use the same 480 held-out windows, making their differences directly comparable within this benchmark.')
p('The evidence and discrepancy gate accepts 458 windows, or 95.42% of the test set. Its selective accuracy is 444/458 = 96.94%, while 14 incorrect windows remain accepted. The gate rejects 22 windows, of which four would have received an incorrect coarse class. Thus it modestly improves accuracy among accepted windows but does not eliminate confident mistakes. Acceptance must be interpreted as nominal model consistency, rather than evidence of a uniquely correct physical explanation.')

h('5.3 Parameter estimates and interval calibration',2)
pars=list(csv.DictReader((R/'parameter_estimates.csv').open()));uro=[]
for u in S['uncertainty']:
    k=u['parameter'];fac={'xc':1000,'r':600,'xd':1000,'ld':1000}[k]
    rr=[r for r in pars if r['parameter']==k];raw=np.mean([abs(float(r['estimate'])-float(r['truth']))<=1.96*float(r['standard_error']) for r in rr])
    label={'xc':'Crack centre','r':'Equivalent crack depth','xd':'Debond centre','ld':'Debond length'}[k]
    uro.append([label,str(u['n']),f'{u["mae"]*fac:.2f}',f'{u["rmse"]*fac:.2f}',pct(raw),pct(u['coverage']),f'{u["median_width"]*fac:.2f}'])
table(7,'Conditional parameter accuracy and interval coverage on correctly classified synthetic test windows. Errors and interval widths are in millimetres.',
      ['Parameter','n','MAE','RMSE','Raw 95% coverage (%)','Scaled coverage (%)','Median scaled width'],uro,
      [1.49,.40,.62,.68,1.12,1.12,1.07],fontsize=9,leftcols=(0,))
p('The crack-position mean absolute error is 1.28 mm over 230 correctly classified crack-bearing windows. The equivalent crack-depth mean absolute error is 0.29 mm, while debond centre and length errors are 2.57 mm and 5.63 mm over 227 correctly classified bond-bearing windows. Sub-pitch localization follows from fitting continuous positions to several spatial samples; it does not mean that the device has independently demonstrated millimetre physical resolution.')
p('Uncalibrated 1.96-standard-error intervals cover only 62.17% of crack centres and 67.83% of equivalent crack depths. This undercoverage is scientifically significant despite small point errors. Validation yields scales of 6.93, 4.08, 2.70 and 2.99 for crack centre, depth ratio, debond centre and debond length, respectively. After applying those independently selected scales, test coverage is 96.09%, 96.09%, 98.24% and 97.80%. The large crack scales show that a local Jacobian alone can be overconfident under the numerical and shared-reference discrepancies.')
fig(8,'fig08_parameter_intervals','Conditional synthetic parameter estimates against known generator values. Selected points are displayed for legibility, with validation-scaled local intervals; coverage values use all eligible cases in Table 7. The diagonal is exact agreement. These are equivalent model parameters, not directly measured crack dimensions.')
p('The intervals are marginal calibration results within the nominal synthetic generator. They exclude incorrectly classified states and do not establish a guaranteed 95% coverage rule for real data. Before physical deployment, calibration must use independent, labelled crack and attachment-defect tests, including states that are close to the diagnostic limit and conditions in which the model catalogue is incomplete.')

h('5.4 Sensitivity and loss of identifiability',2)
p('Figure 9 compares scaled Jacobian conditioning with and without the witness route for the illustrated crack depth. Overlapping mechanisms create weak directions in which debond length, debond centre and crack amplitude compensate each other. For a 600 mm debond centred on the crack, the ratio increases from 0.016 to 0.215 when the witness is added. The second route provides a host-crack observation unaffected by the suspect bond. The ratio does not increase everywhere: for a 50 mm debond separated by 800 mm, it changes from 0.037 to 0.026. Because this measure normalizes the weakest sensitivity by the strongest, an added observation can increase both unequally. It should be read alongside the route-ablation errors rather than as a monotone information score. Sensitivity remains conditional on load pattern, transfer length and the selected parameter scales.')
fig(9,'fig09_identifiability','Local singular-value ratios for synthetic joint states, with three diagnostic loads. The Jacobian is noise-whitened, nuisance-profiled and scaled as in Eq. (22). Higher ratios indicate better local conditioning within the assumed model; the colour range is shared between panels. This local audit is not a proof of global uniqueness.')
p('An important distinction is that local well-conditioning around a detected fault does not ensure observability of every alternative undetected fault. A healthy prediction can arise from a weak signal or from a truly invariant sensing configuration. The constant-moment example in Section 5.7 makes this distinction explicit. Uniform or nearly uniform host strain does not strongly excite an intact fibre bridge over a bond-loss interval.')

h('5.5 Noise model mismatch and witness failure',2)
challenge=[]
for m in S['noise']:challenge.append([f'Noise σ = {m["sigma"]:.2f} µε',str(m['n']),pct(m['balanced_accuracy']),str(m['correct'])+' / 80','—'])
for key,gkey,name,n in [('mismatch','mismatch_gate','Combined model mismatch',80),('shared','shared_gate','Shared debond on both routes',64),('no_temperature','no_temperature_gate','Temperature reference omitted',80)]:
    m=S[key];g=S[gkey]
    score='Outside catalogue' if key=='shared' else pct(m['balanced_accuracy'])
    challenge.append([name,str(n),score,f'{g["accepted"]} / {n}',f'{g["wrong_confident"]} / {n}'])
table(8,'Executed challenge results. Noise rows show the correct count; other rows show gate acceptance. Wrong accepted counts refer to the coarse four-state label and do not certify model adequacy.',
      ['Challenge','n','Balanced accuracy (%)','Correct or accepted count','Wrong accepted count'],challenge,
      [2.15,.35,1.20,1.45,1.35],fontsize=9,leftcols=(0,))
p('On the fixed 80-configuration subset, balanced accuracy decreases from 100.00% at σ = 0.25 µε to 93.75%, 86.25% and 76.25% at 0.75, 1.50 and 3.00 µε. The 100.00% result is 80/80 correct at one prescribed low-noise setting; it is not evidence of universal perfect diagnosis. Each challenge draws new noise and temperature coefficients, so its 0.75 µε result need not equal the 96.25% result on all 480 original test windows.')
p('Combined model mismatch reduces balanced accuracy to 85.00%. The nominal gate accepts 53/80 windows and eight wrong coarse labels remain accepted, or 10.00% of the challenge. The gate therefore fails to correct some physically plausible but biased explanations. A nominal covariance and validation scale should not be treated as a substitute for model-form uncertainty. Joint estimation of bond parameters, gauge settings and structural nuisance quantities would require additional calibration information to avoid merely expanding the inverse ambiguity.')
p('Shared debonding on both routes breaks the central witness assumption. The gate rejects 59 of 64 windows, or 92.19%, but accepts five. Four accepted windows have wrong coarse state labels. The fifth happens to receive Hcd, yet its route-B attachment defect is still omitted from the model. All five acceptances are therefore failures to recognize an out-of-catalogue attachment topology. This challenge supports independent attachment inspection or an additional sensing modality rather than reliance on redundant fibres alone.')
fig(10,'fig10_robustness','Executed synthetic noise and mismatch challenges. The shaded band in panel (a) is a 95% stratified-bootstrap interval. In panel (b), wrong-and-accepted refers to coarse class errors; all five accepted shared-debond cases are outside the model catalogue, including the case whose coarse label matches.')
p('Without temperature-reference compensation, accuracy is 38.75% and 17 of 20 healthy windows receive a false damage label. Only one of the 80 windows passes the residual and evidence gate. This experiment isolates the need to distinguish structural change from a thermal spectral shift under the chosen acquisition drift. It does not show that the proposed coefficient model is sufficient for real bridge temperature gradients, transient heat transfer or differential thermal bending.')

h('5.6 Sequential virtual fatigue monitoring',2)
p('The prescribed Paris stream grows from 12.00 to 50.84 mm equivalent crack depth over 6 million cycles. The Markov-filtered coarse class matches 40 of the 41 true windows; 38 snapshots satisfy the nominal evidence and discrepancy gate. The bond defect first appears at window 20, and the filtered joint state is declared at window 21. The delay is one acquisition window, corresponding to 150,000 prescribed cycles. It is a property of this constructed stream and cannot be translated into a real-time bridge warning delay.')
fig(11,'fig11_sequential_twin','Executed 41-window synthetic fatigue stream. Parameters are current fits conditioned on the filtered class. Red crosses mark snapshots that do not pass the nominal evidence and discrepancy gate. The vertical line is prescribed debond onset. The Paris law generates the truth stream and is not an input to snapshot inverse diagnosis.')
p('At the final window, the conditional fit estimates 50.90 mm crack depth and 321.01 mm debond length, compared with generator values of 50.84 mm and 320.00 mm. The stream illustrates repeated state updating and separation of crack progression from a later attachment defect. It is not a validation of the Paris constant, traffic damage accumulation or residual life. Repair, crack closure and attachment recovery would require an expanded transition model; the present monotone-state assumption would be unsuitable after an intervention.')
p(f'The median four-model fitting time is {S["timing_median_s"]:.3f} s per held-out window and the 95th-percentile time is {S["timing_p95_s"]:.3f} s on the execution host. The full numerical study took {S["runtime_s"]:.1f} s, excluding manuscript assembly. These are measured software timings. Interrogation time, movement between known load positions, network transfer, calibration and bridge operational constraints are excluded, so an end-to-end real-time capability is not established.')

h('5.7 An optically invisible debond counterexample',2)
p('The fibre equation exposes a blind spot independent of classifier choice. In an interior region with uniform host strain ε₀ and compatible anchorage, the fibre displacement u₍f₎ = ε₀x + constant satisfies both the bonded equilibrium and the traction-free debond equation. Removing a local shear foundation does not require the fibre strain to change if the surrounding host displacements remain collinear. Consequently, the derivative of the observed strain with respect to debond length vanishes in this ideal configuration.')
eq(r'u_h=\epsilon_0x+c_0,\quad u_f=u_h\ \Longrightarrow\ \bar{\epsilon}_f=\epsilon_0,\quad \frac{\partial\bar{\epsilon}_f}{\partial\ell_d}=0',28)
p('The numerical counterexample applies equal point loads at 2 and 6 m simultaneously, creating a constant-moment interior region. A 400 mm debond at 4 m changes the calculated strain by at most 7.05 × 10⁻¹¹ µε over the observed interval, within numerical precision for this model. The two independently loaded configurations at 2 and 6 m instead create opposing local gradients, and the same defect then produces visible, opposite-signed residuals. The central load also changes the signature near its moment-gradient kink.')
fig(12,'fig12_blind_spot','Executed synthetic counterexample. A 400 mm attachment defect is practically invisible when it lies inside the uniform-moment region under simultaneous four-point loading. Separate diagnostic loads change the host strain gradients and expose the bond loss. The counterexample concerns the nominal shear-foundation model and compatible fibre bridging.')
p('This result prevents an overinterpretation of the high nominal test accuracy. Neither a digital twin nor a more expressive classifier can infer a defect that leaves its input unchanged. The operational implication is to report the loads under which a sensing attachment is observable and to separate absence of a detected anomaly from confirmation of bond integrity. The ideal counterexample is a derivation within the present reduced model, not a claim that all physical debonds are invisible under four-point bending.')

h('6 Scope limitations and the next validation step')
p('The main scientific limitation is shared model structure. Truth generation and inversion use different discretizations and interface treatments, but both inherit the same beam and shear-foundation equations. The high nominal accuracy therefore evaluates diagnosis conditional on those mechanics. The independent Hermite assembly, mesh refinement and mismatch challenges are useful numerical checks, but they do not replace a crack-opening measurement, a fibre pull-out or peel calibration, or a laboratory girder test.')
p('The equivalent rectangular crack surrogate neglects welded detail geometry, three-dimensional stress redistribution, torsion, shear deformation, residual stresses, yielding and crack closure. A shallow notch in a laboratory strip and a fatigue crack in a bridge flange need not have the same compliance or displacement transfer. Equivalent crack-depth errors in Table 7 cannot be used as physical crack-sizing guarantees for a welded bridge detail. Unknown traffic loads and support flexibility are also excluded from the nominal inverse inputs.')
p('Attachment behaviour is reduced to a single effective foundation stiffness and one defect interval. Real adhesives can exhibit hysteresis, frictional slip, temperature-dependent stiffness and gradual fatigue deterioration. The 5% residual-stiffness challenge tests only one departure from the nominal law. The witness challenge demonstrates that correlated attachment damage is a concrete failure mechanism. An extended catalogue with separate bond states on both routes may fit more cases, but without an independent reference it can reintroduce structural–sensor ambiguity.')
p('The observation model assumes usable spectral shifts at every gauge. Experiments on resolution and strain-gradient limitations [2] show why this assumption needs interrogator-specific qualification. A physical evaluation should preserve spectral-correlation quality, missing data and actual temperature-reference errors, rather than substituting ideal strain arrays. The 25 mm pitch is a numerical sampling choice and the 50 mm gauge is a selected averaging length; neither is a commercial-device specification established by this study.')
p('A focused laboratory validation can test the mechanism rather than merely repeat the numerical benchmark. A steel girder strip with two separately bonded routes should first be calibrated in healthy loading. Crack-only, attachment-only, overlapping and shared-attachment states should then be measured under several known load locations. Independent crack-opening and bond-length measurements would provide ground truth. The parameter and residual calibration must use separate specimens or loading histories, and all spatial samples from a history must remain in the same split. Such work is proposed here and has not been completed.')
p('For bridge-scale translation, the reduced twin should be calibrated against a three-dimensional structural model and measured temperature/load histories, with explicit model-form uncertainty and shared route covariance. A deployment claim would further require long-duration attachment durability and interrogator-quality data. The present computational study provides a reproducible test bed and failure analysis for that programme.')

h('7 Conclusions')
p('This study develops and executes a physics-informed virtual digital twin for joint diagnosis of a girder crack and local fibre debonding. The method couples rotational crack compliance, fibre-transfer equilibrium, finite-gauge optical shifts and constrained model comparison. Its principal evidence is a controlled synthetic benchmark with withheld damage locations, rather than measurements from a physical bridge.')
p('Two independently bonded routes materially improve joint-fault discrimination: balanced accuracy is 96.25% with both routes and three known loads, compared with 87.08% with one route. The stronger morphology random forest reaches 92.08%, and the paired benchmark accuracy gain is 4.17 percentage points. Conditional equivalent-parameter errors are small, but uncalibrated crack intervals under-cover; separate validation scales are needed to reach the reported nominal coverage. The residual gate retains incorrect accepted diagnoses and cannot establish unique causation.')
p('Model mismatch reduces accuracy to 85.00%, shared bond degradation defeats the witness assumption, and a uniform-moment example produces an effectively unchanged optical profile despite a 400 mm debond. These results make observability and model adequacy part of the scientific conclusion. The proposed advance is a transparent joint-fault inference and failure benchmark, with executed code and retained data. Independent physical calibration and validation are needed before claims of bridge-level crack sizing, warning performance or remaining-life prediction.')

h('Acknowledgements')
p('Generative AI assistance through ChatGPT (OpenAI) was used in developing the computational workflow, drafting the manuscript and preparing original schematic figures. All quantitative results reported here were produced by the supplied, executed Python numerical code. This draft requires independent author verification and approval before submission.')
h('Statements and Declarations')
h('Ethical considerations',2)
p('Not applicable. The study uses generated structural and optical data and involves no human participants, human data or animals.')
h('Consent to participate',2)
p('Not applicable.')
h('Consent for publication',2)
p('Not applicable to the generated data and illustrations. Author consent to submit the manuscript must be obtained separately.')
h('Declaration of conflicting interest',2)
p('[To be completed and confirmed by all authors before submission.]')
h('Funding statement',2)
p('[Authors must confirm funding sources and grant numbers, or confirm that no external funding was received.]')
h('Data availability',2)
p('The simulation code, configurations, generated observation arrays, numerical results, bootstrap outputs and original figure files are included in the accompanying Bridge_Girder_Digital_Twin_Reproducibility.zip package. No observational bridge dataset is used. No public repository DOI is claimed; a persistent public deposition may be added by the submitting authors.')

h('References')
refs=[
'Froggatt M, Moore J. High-spatial-resolution distributed strain measurement in optical fiber with Rayleigh scatter. Appl Opt 1998; 37(10): 1735–1740. DOI: 10.1364/AO.37.001735.',
'Herbers M, Richter B, Marx S. Rayleigh-based crack monitoring with distributed fiber optic sensors: experimental study on the interaction of spatial resolution and sensor type. J Civ Struct Health Monit 2025; 15: 1439–1463. DOI: 10.1007/s13349-024-00896-5.',
'Ansari F, Libo Y. Mechanics of bond and interface shear transfer in optical fiber sensors. J Eng Mech 1998; 124(4): 385–394. DOI: 10.1061/(ASCE)0733-9399(1998)124:4(385).',
'Falcetelli F, Rossi L, Di Sante R, et al. Strain transfer in surface-bonded optical fiber sensors. Sensors 2020; 20(11): 3100. DOI: 10.3390/s20113100.',
'Bassil A, Chapeleau X, Leduc D, et al. Concrete crack monitoring using a novel strain transfer model for distributed fiber optics sensors. Sensors 2020; 20(8): 2220. DOI: 10.3390/s20082220.',
'Chapeleau X, Bassil A. A general solution to determine strain profile in the core of distributed fiber optic sensors under any arbitrary strain fields. Sensors 2021; 21(16): 5423. DOI: 10.3390/s21165423.',
'Zhang S, Liu H, Cheng J, et al. A mechanical model to interpret distributed fiber optic strain measurement at displacement discontinuities. Struct Health Monit 2021; 20(5): 2584–2603. DOI: 10.1177/1475921720964183.',
'Tan X, Mahjoubi S, Zou X, et al. Metaheuristic inverse analysis on interfacial mechanics of distributed fiber optic sensors undergoing interfacial debonding. Mech Syst Signal Process 2023; 200: 110532. DOI: 10.1016/j.ymssp.2023.110532.',
'Lin SQ, Tan DY, Yin JH, et al. Distributed fiber optic sensing for micro- and macro-crack quantification: an interfacial-fracture-energy-based model. Struct Health Monit 2024; 23(5): 2815–2833. DOI: 10.1177/14759217231215482.',
'Zhao L, You R, Ren L. Inverse finite element method and support vector regression for automated crack detection with OFDR-Distributed fiber optic sensors. Measurement 2024; 234: 114916. DOI: 10.1016/j.measurement.2024.114916.',
'Chen S, Xu H, Zhao S, et al. Fatigue crack prediction based on distributed optical fiber sensing data and dynamic Bayesian network. Measurement 2025; 255: 118070. DOI: 10.1016/j.measurement.2025.118070.',
'Dong Y, Zhang S, Li Q, et al. Distributed optical fiber strain field reconstruction method for prefabricated beam bridges based on a physics-guided PINN. Sens Mater 2026; 38(3): 1153–1179. DOI: 10.18494/SAM6097.',
'Andrés Arcones D, Paul A, Weiser M, et al. Bayesian tendon breakage localization under model uncertainty using distributed fiber optic sensors. Data-Centric Engineering 2026; 7: e46. DOI: 10.1017/dce.2026.10077.',
'Patil DP, Maiti SK. Experimental verification of a method of detection of multiple cracks in beams based on frequency measurements. J Sound Vib 2005; 281(1–2): 439–451. DOI: 10.1016/j.jsv.2004.03.035.',
'Schwarz G. Estimating the dimension of a model. Ann Stat 1978; 6(2): 461–464. DOI: 10.1214/aos/1176344136.',
'Breiman L. Random forests. Mach Learn 2001; 45: 5–32. DOI: 10.1023/A:1010933404324.',
'Paris P, Erdogan F. A critical analysis of crack propagation laws. J Basic Eng 1963; 85(4): 528–533. DOI: 10.1115/1.3656900.',
'Virtanen P, Gommers R, Oliphant TE, et al. SciPy 1.0: fundamental algorithms for scientific computing in Python. Nat Methods 2020; 17: 261–272. DOI: 10.1038/s41592-019-0686-2.',
'Pedregosa F, Varoquaux G, Gramfort A, et al. Scikit-learn: machine learning in Python. J Mach Learn Res 2011; 12: 2825–2830. https://www.jmlr.org/papers/v12/pedregosa11a.html.'
]
for i,ref in enumerate(refs,1):
    q=p(f'{i}. {ref}',align=WD_ALIGN_PARAGRAPH.LEFT);q.paragraph_format.left_indent=Inches(.25);q.paragraph_format.first_line_indent=Inches(-.25)
    q.paragraph_format.space_after=Pt(5)
    for run in q.runs:run.font.size=Pt(10)

# Fix all font names and colours including title/header/footer direct formatting.
for paragraph in list(doc.paragraphs)+list(sec.header.paragraphs)+list(sec.footer.paragraphs):
    for run in paragraph.runs:
        run.font.color.rgb=RGBColor(0,0,0)
doc.core_properties.title=TITLE;doc.core_properties.subject='Executed synthetic joint crack and fibre debonding diagnosis'
doc.core_properties.author='';doc.core_properties.keywords='distributed optical fibre; digital twin; crack; debonding; computational study'
doc.core_properties.comments='Research draft. Author metadata and declarations remain to be confirmed. Synthetic results only.'
DEST.parent.mkdir(exist_ok=True);doc.save(DEST)
text='\n'.join(p.text for p in doc.paragraphs)
with zipfile.ZipFile(DEST) as z:xml=z.read('word/document.xml').decode()
audit={'path':str(DEST),'equation_numbers':EQ,'native_equation_count':xml.count('<m:oMath>'),
       'figures':CAPS,'tables':TABLES,'references':len(refs),'paragraph_word_count':len(text.split()),
       'author_status':'unconfirmed','result_status':'executed synthetic benchmark'}
(ROOT/'manuscript_audit.json').write_text(json.dumps(audit,indent=2));(ROOT/'manuscript_text.txt').write_text(text)
print(json.dumps({k:v for k,v in audit.items() if k not in ['figures','tables']},indent=2))
