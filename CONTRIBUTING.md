# 参与开发

自动测试只使用合成后端，不会自动连接钱迹或记账。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip install --no-deps .
.venv/bin/python -m unittest discover -s tests -q
```

涉及金额、版本、挂起恢复或账户依赖的修改，请补充复现原问题的合成测试，保留稳定请求编号、字段回读和自然余额核验。不要提交真实账单、登录态、操作记录库或私人验收材料。

App更新后的适配应重新核验公开适配文件和后台合同；合成测试通过不等于原生实账验收通过。
