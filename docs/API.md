# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

复核决策为已复核时，同一事务内冻结签证原件v1，之后不再改写。`GET /api/certificates/<id>/visa`返回工作台视图：唯一现行签证、对账差异（现行−原件）与补正依据；未签认返回404。`POST /api/certificates/<id>/corrections`登记补正，body为`{"items":[{"claim_id","expected"}],"basis":{"reason","evidence"}}`；成功升版返回201，同一补正（内容幂等键相同）重试返回200且不新增版本。未签认、引用不存在、净额无变化、依据缺失分别返回NOT_CERTIFIED、UNKNOWN_REFERENCE、NO_CHANGE、BAD_BASIS。
