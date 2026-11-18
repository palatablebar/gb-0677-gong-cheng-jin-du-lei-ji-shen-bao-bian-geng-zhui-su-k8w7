from flask import Blueprint,request,jsonify
from app.errors import DomainError
from app.pipeline import stage_preview
from app import store
from app.visa import correct,workbench
bp=Blueprint("certificates",__name__)
@bp.route("/api/certificates",methods=["GET","POST"])
def preview():
    payload=request.get_json(silent=True) if request.method=="POST" else {}
    if payload is None or not isinstance(payload,dict): raise DomainError("BAD_BODY","请求需要对象")
    return jsonify(stage_preview(6,payload))
@bp.get("/api/certificates/<run_id>/visa")
def visa_state(run_id):
    store.get(run_id)
    state=workbench(run_id)
    if state is None: raise DomainError("NOT_CERTIFIED","签证未签认，不能补正",404)
    return jsonify({"visa":state})
@bp.post("/api/certificates/<run_id>/corrections")
def correct_visa(run_id):
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict): raise DomainError("BAD_BODY","请求需要对象")
    result=correct(store.get(run_id),payload.get("items"),payload.get("basis"))
    return jsonify(result),201 if result["created"] else 200
