import pytest
from app import store
from app.errors import DomainError
from app.pipeline import execute
from app.visa import correct,workbench
BASIS={"reason":"扣回比例按补充协议调整","evidence":"补充协议BG-2026-018"}
ITEM={"claim_id":"00001","expected":"2000.00"}
@pytest.fixture
def signed(sample):
    run=execute(sample)
    store.review(run["run_id"],run["version"],"已复核")
    return store.get(run["run_id"])
def test_sign_freezes_original(signed):
    visa=workbench(signed["run_id"])
    assert visa["versions"]==1 and visa["current_version"]==1
    assert visa["current"]["net_total"]=="68425.00" and visa["reconciliation"]["rows"]==[]
def test_correction_issues_new_current_and_keeps_original(signed):
    result=correct(signed,[ITEM],BASIS)
    assert result["created"] is True
    visa=result["visa"]
    assert visa["versions"]==2 and visa["current_version"]==2
    assert visa["current"]["net_total"]=="68300.00"
    assert visa["original"]["net_total"]=="68425.00"
    row=next(r for r in visa["current"]["rows"] if r["claim_id"]=="00001")
    assert row["expected"]=="2000.00" and row["status"]=="通过" and row["corrected"] is True
def test_same_correction_retry_adds_no_version(signed):
    first=correct(signed,[ITEM],BASIS)
    again=correct(signed,[ITEM],BASIS)
    assert again["created"] is False
    assert again["visa"]["versions"]==2 and first["visa"]["current"]["sha256"]==again["visa"]["current"]["sha256"]
def test_distinct_correction_adds_version(signed):
    correct(signed,[ITEM],BASIS)
    result=correct(signed,[{"claim_id":"00003","expected":"2100.00"}],BASIS)
    assert result["created"] is True and result["visa"]["versions"]==3
    assert result["visa"]["current"]["net_total"]=="68275.00"
def test_correction_requires_certified(sample):
    run=execute(sample)
    with pytest.raises(DomainError) as e: correct(run,[ITEM],BASIS)
    assert e.value.code=="NOT_CERTIFIED"
def test_correction_unknown_claim(signed):
    with pytest.raises(DomainError) as e: correct(signed,[{"claim_id":"99999","expected":"1.00"}],BASIS)
    assert e.value.code=="UNKNOWN_REFERENCE"
def test_correction_without_change_rejected(signed):
    with pytest.raises(DomainError) as e: correct(signed,[{"claim_id":"00001","expected":"2125.00"}],BASIS)
    assert e.value.code=="NO_CHANGE"
def test_correction_requires_basis(signed):
    with pytest.raises(DomainError) as e: correct(signed,[ITEM],{"reason":"","evidence":"x"})
    assert e.value.code=="BAD_BASIS"
def test_correction_bad_amount(signed):
    with pytest.raises(DomainError) as e: correct(signed,[{"claim_id":"00001","expected":"abc"}],BASIS)
    assert e.value.code=="INVALID_NUMBER"
def test_reconciliation_matches_original(signed):
    correct(signed,[ITEM],BASIS)
    visa=workbench(signed["run_id"])
    recon=visa["reconciliation"]
    assert recon["original_total"]=="68425.00" and recon["current_total"]=="68300.00" and recon["delta_total"]=="-125.00"
    assert recon["rows"]==[{"claim_id":"00001","item":"001","period":"2026-01","original":"2125.00","current":"2000.00","delta":"-125.00"}]
    assert visa["corrections"][0]["basis"]==BASIS and visa["corrections"][0]["delta"]=="-125.00"
def test_resign_never_overwrites_original(signed):
    correct(signed,[ITEM],BASIS)
    run=store.get(signed["run_id"])
    store.review(run["run_id"],run["version"],"已复核")
    visa=workbench(signed["run_id"])
    assert visa["versions"]==2 and visa["original"]["net_total"]=="68425.00"
def test_e2e_correction_flow(client):
    run=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    assert client.get("/api/certificates/"+run["run_id"]+"/visa").status_code==404
    client.post("/api/runs/"+run["run_id"]+"/review",json={"version":1,"decision":"已复核"})
    url="/api/certificates/"+run["run_id"]+"/corrections"
    body={"items":[ITEM],"basis":BASIS}
    assert client.post(url,json=body).status_code==201
    retry=client.post(url,json=body)
    assert retry.status_code==200 and retry.get_json()["created"] is False
    visa=client.get("/api/certificates/"+run["run_id"]+"/visa").get_json()["visa"]
    assert visa["versions"]==2 and visa["current"]["net_total"]=="68300.00"
    assert client.get("/certificates").status_code==200
def test_e2e_correction_validates_body(client):
    run=client.post("/api/runs",json={"sample":"dirty.csv"}).get_json()
    client.post("/api/runs/"+run["run_id"]+"/review",json={"version":1,"decision":"已复核"})
    url="/api/certificates/"+run["run_id"]+"/corrections"
    assert client.post(url,json={"items":[],"basis":BASIS}).status_code==422
    assert client.post(url,json={"items":[ITEM]}).status_code==422
