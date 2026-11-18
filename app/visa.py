import hashlib,json,sqlite3
from datetime import datetime,timezone
from decimal import Decimal
from app import store
from app.errors import DomainError
from app.values import money,number
def _now(): return datetime.now(timezone.utc).isoformat()
def _seal(rows): return hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
def _payload(rows):
    rows=[dict(r) for r in rows]
    total=sum((number(r.get("expected","0")) for r in rows),Decimal(0))
    return {"rows":rows,"records":len(rows),"net_total":money(total),"sha256":_seal(rows)}
def _versions(db,run_id):
    return db.execute("SELECT version,correction_key,basis,payload,created_at FROM visas WHERE run_id=? ORDER BY version",(run_id,)).fetchall()
def freeze_signed(db,run_id,run):
    "签认事务内冻结原件v1；已存在则保持原样，绝不覆盖。"
    db.execute("INSERT OR IGNORE INTO visas(run_id,version,correction_key,basis,payload,created_at) VALUES (?,?,?,?,?,?)",
        (run_id,1,"","{}",json.dumps(_payload(run["stages"][-1]["rows"]),ensure_ascii=False),_now()))
def _validate(items,basis):
    if not isinstance(items,list) or not items: raise DomainError("BAD_CORRECTION","补正需要至少一条更正项")
    if not isinstance(basis,dict) or not str(basis.get("reason","")).strip() or not str(basis.get("evidence","")).strip():
        raise DomainError("BAD_BASIS","补正依据需含更正原因与凭证文号")
    clean=[];seen=set()
    for item in items:
        if not isinstance(item,dict): raise DomainError("BAD_CORRECTION","更正项需要对象")
        claim=str(item.get("claim_id","")).strip()
        if not claim: raise DomainError("EMPTY_VALUE","更正项缺少申报编号")
        if claim in seen: raise DomainError("BAD_CORRECTION","同一申报编号重复更正")
        seen.add(claim);clean.append({"claim_id":claim,"expected":money(item.get("expected"))})
    return clean,{"reason":str(basis["reason"]).strip(),"evidence":str(basis["evidence"]).strip()}
def _key(run_id,items,basis):
    canonical={"run_id":run_id,"items":sorted([i["claim_id"],i["expected"]] for i in items),"basis":basis}
    return hashlib.sha256(json.dumps(canonical,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def correct(run,items,basis):
    "登记补正：现行签证升版，原件不动；同一补正重试不新增版本。"
    run_id=run["run_id"];items,basis=_validate(items,basis)
    with store.connect() as db:
        versions=_versions(db,run_id)
        if not versions: raise DomainError("NOT_CERTIFIED","签证未签认，不能补正")
        key=_key(run_id,items,basis)
        if any(v[1]==key for v in versions): return {"created":False,"visa":workbench(run_id,db)}
        rows=[dict(r) for r in json.loads(versions[-1][3])["rows"]]
        by_claim={str(r.get("claim_id")):r for r in rows}
        for item in items:
            if item["claim_id"] not in by_claim: raise DomainError("UNKNOWN_REFERENCE","更正项引用不存在的申报编号")
        changed=False
        for item in items:
            row=by_claim[item["claim_id"]]
            if str(row.get("expected"))!=item["expected"]: changed=True
            row["expected"]=item["expected"];row["corrected"]=True
            delta=number(item["expected"])-number(row.get("reported","0"))
            row["difference"]=str(delta);row["status"]="通过" if delta==0 else "差异"
        if not changed: raise DomainError("NO_CHANGE","补正未改变现行净额")
        try:
            db.execute("INSERT INTO visas(run_id,version,correction_key,basis,payload,created_at) VALUES (?,?,?,?,?,?)",
                (run_id,versions[-1][0]+1,key,json.dumps(basis,ensure_ascii=False),json.dumps(_payload(rows),ensure_ascii=False),_now()))
        except sqlite3.IntegrityError:
            if db.execute("SELECT 1 FROM visas WHERE run_id=? AND correction_key=?",(run_id,key)).fetchone():
                return {"created":False,"visa":workbench(run_id,db)}
            raise DomainError("CONCURRENT_CORRECTION","并发补正冲突，请刷新后重试",409)
    return {"created":True,"visa":workbench(run_id)}
def workbench(run_id,db=None):
    "工作台视图：唯一现行签证、对账差异、补正依据。未签认返回None。"
    own=db is None
    if own: db=store.connect()
    try: versions=_versions(db,run_id)
    finally:
        if own: db.close()
    if not versions: return None
    chain=[{"version":v[0],"correction_key":v[1],"basis":json.loads(v[2]),"payload":json.loads(v[3]),"created_at":v[4]} for v in versions]
    original,current=chain[0],chain[-1]
    base={str(r.get("claim_id")):r for r in original["payload"]["rows"]}
    diffs=[]
    for row in current["payload"]["rows"]:
        old=number(base.get(str(row.get("claim_id")),{}).get("expected","0"));new=number(row.get("expected","0"))
        if old!=new: diffs.append({"claim_id":row.get("claim_id"),"item":row.get("item",""),"period":row.get("period",""),"original":money(old),"current":money(new),"delta":str(new-old)})
    corrections=[];previous=original
    for v in chain[1:]:
        corrections.append({"version":v["version"],"correction_key":v["correction_key"],"basis":v["basis"],"created_at":v["created_at"],
            "net_total":v["payload"]["net_total"],"delta":str(number(v["payload"]["net_total"])-number(previous["payload"]["net_total"]))})
        previous=v
    return {"run_id":run_id,"versions":len(chain),"current_version":current["version"],
        "current":{**current["payload"],"created_at":current["created_at"]},
        "original":{**original["payload"],"created_at":original["created_at"]},
        "corrections":corrections,
        "reconciliation":{"rows":diffs,"original_total":original["payload"]["net_total"],"current_total":current["payload"]["net_total"],
            "delta_total":str(number(current["payload"]["net_total"])-number(original["payload"]["net_total"]))}}
