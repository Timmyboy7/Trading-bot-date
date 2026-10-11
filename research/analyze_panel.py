import csv, statistics as st, math, collections, sys
import os
P=os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_round2_panel.csv")
def f(x):
    try: return float(x)
    except: return None
rows=list(csv.DictReader(open(P)))
by=collections.defaultdict(list); spy={}
for r in rows:
    for k in ("momentum_score","ret_3m_back","ret_6m_back","ret_12_1_back","vol_12m","rel_upside_pct","upside_pct","fwd_1m","fwd_3m","fwd_6m"): r[k]=f(r[k])
    if r["symbol"]=="SPY": spy[r["month"]]=r
    else: by[r["month"]].append(r)
months=sorted(by)
print("rows",len(rows),"months",len(months),months[0],months[-1],"avg members/month",round(st.mean(len(v) for v in by.values())))
def pick(cands,key,n=20,cap=5):
    out=[];per=collections.Counter()
    for r in sorted(cands,key=key,reverse=True):
        if per[r["sector"]]>=cap: continue
        out.append(r);per[r["sector"]]+=1
        if len(out)==n: break
    return out
def wret(b,w,h="fwd_6m"):
    pairs=[(x,r[h]) for x,r in zip(w,b) if r[h] is not None]
    s=sum(x for x,_ in pairs); return sum(x*y for x,y in pairs)/s if s else None
# check reproduction
ex=[]
for m in months:
    c=[r for r in by[m] if r["ret_12_1_back"] is not None]
    b=pick(c,lambda r:r["ret_12_1_back"])
    ret=st.mean([r["fwd_6m"] for r in b if r["fwd_6m"] is not None]); ex.append(ret-spy[m]["fwd_6m"])
print("repro momentum_12_1 6m excess", round(st.mean(ex)*100,2))

def summ(fn, h="fwd_6m"):
    ex=[]; reg=collections.defaultdict(list)
    for m in months:
        r=fn(m)
        if r is None or spy[m][h] is None: continue
        e=r-spy[m][h]; ex.append(e); reg[m[:4]].append(e)
    regs={"21-22":[x for y in ("2021","2022") for x in reg[y]],"23-24":[x for y in ("2023","2024") for x in reg[y]],"25-26":[x for y in ("2025","2026") for x in reg[y]]}
    return round(st.mean(ex)*100,2), round(sum(e>0 for e in ex)/len(ex),2), {k:round(st.mean(v)*100,1) for k,v in regs.items()}

print("\nA) 12-1 momentum quintiles (all members) -> avg 6m return minus SPY")
for q in range(5):
    def fq(m,q=q):
        c=sorted([r for r in by[m] if r["ret_12_1_back"] is not None and r["fwd_6m"] is not None],key=lambda r:r["ret_12_1_back"])
        n=len(c); s=c[q*n//5:(q+1)*n//5]; return st.mean(r["fwd_6m"] for r in s)
    print(" Q%d (%s)"%(q+1,"lowest" if q==0 else "highest" if q==4 else ""), summ(fq))
print("\nA2) volatility quintiles (all members)")
for q in range(5):
    def fv(m,q=q):
        c=sorted([r for r in by[m] if r["vol_12m"] is not None and r["fwd_6m"] is not None],key=lambda r:r["vol_12m"])
        n=len(c); s=c[q*n//5:(q+1)*n//5]; return st.mean(r["fwd_6m"] for r in s)
    print(" V%d (%s)"%(q+1,"calmest" if q==0 else "wildest" if q==4 else ""), summ(fv))

def mom_basket(m,n=20,cap=5,vol_cap=None):
    c=[r for r in by[m] if r["ret_12_1_back"] is not None and r["vol_12m"] is not None]
    if vol_cap: 
        vs=sorted(r["vol_12m"] for r in c); lim=vs[int(len(vs)*vol_cap)-1]; c=[r for r in c if r["vol_12m"]<=lim]
    return pick(c,lambda r:r["ret_12_1_back"],n,cap)
print("\nB) 12-1 momentum basket: size and weighting (6m excess %, beat share, by regime)")
for n in (10,20,30,50):
    print(f" top {n}, equal weight      ", summ(lambda m,n=n: wret(b:=mom_basket(m,n),[1]*len(b))))
for name,wf in [("rank-weighted (stronger signal = more)",lambda b:[len(b)-i for i in range(len(b))]),
                ("inverse-volatility (calmer = more)",lambda b:[1/r["vol_12m"] for r in b]),
                ("signal x inverse-vol",lambda b:[(len(b)-i)/r["vol_12m"] for i,r in enumerate(b)])]:
    print(f" top 20, {name}", summ(lambda m,wf=wf: wret(b:=mom_basket(m),wf(b))))
print(" top 20 among calmer 80% (drop wildest 20%)", summ(lambda m: wret(b:=mom_basket(m,vol_cap=0.8),[1]*len(b))))
print(" top 20 among calmer 60%", summ(lambda m: wret(b:=mom_basket(m,vol_cap=0.6),[1]*len(b))))

print("\nD) Realistic: rebalance every 6 months, compounded, average over the 6 possible start months")
def sim(fn):
    res=[]
    for off in range(6):
        eq=1.0; sp=1.0; peak=1.0; mdd=0; steps=0
        for m in months[off::6]:
            r=fn(m); s=spy[m]["fwd_6m"]
            if r is None or s is None: continue
            eq*=1+r; sp*=1+s; steps+=1
        yrs=steps/2
        res.append(((eq**(1/yrs)-1)*100,(sp**(1/yrs)-1)*100,steps))
    return round(st.mean(x[0] for x in res),1), round(st.mean(x[1] for x in res),1), [round(x[0]-x[1],1) for x in res]
for name,fn in [("12-1 momentum top 20 equal",lambda m: wret(b:=mom_basket(m),[1]*len(b))),
                ("12-1 momentum top 20 inverse-vol",lambda m: wret(b:=mom_basket(m),[1/r["vol_12m"] for r in b])),
                ("12-1 momentum top 30 equal",lambda m: wret(b:=mom_basket(m,30),[1]*len(b))),
                ("all members equal weight",lambda m: st.mean(r["fwd_6m"] for r in by[m] if r["fwd_6m"] is not None))]:
    a,s,d=sim(fn); print(f" {name:35s} {a:5.1f}%/yr vs SPY {s:5.1f}%/yr | excess per start month {d}")

print("\nE) Risk of the main variants (6-month periods, all start months)")
for name,fn in [("top 10 equal",lambda m: wret(b:=mom_basket(m,10),[1]*len(b))),
                ("top 20 equal",lambda m: wret(b:=mom_basket(m),[1]*len(b))),
                ("top 20 rank-weighted",lambda m: wret(b:=mom_basket(m),[len(b)-i for i in range(len(b))])),
                ("top 20 signal x inv-vol",lambda m: wret(b:=mom_basket(m),[(len(b)-i)/r["vol_12m"] for i,r in enumerate(b)])),
                ("top 30 equal",lambda m: wret(b:=mom_basket(m,30),[1]*len(b))),
                ("SPY",lambda m: spy[m]["fwd_6m"])]:
    rs=[fn(m) for m in months]; rs=[r for r in rs if r is not None]
    ex=[r-spy[m]["fwd_6m"] for r,m in zip(rs,months)]
    print(f" {name:25s} worst 6m {min(rs)*100:6.1f}%  best {max(rs)*100:6.1f}%  sd {st.pstdev(rs)*100:5.1f}%  worst vs SPY {min(ex)*100:6.1f}%")
