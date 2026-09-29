# 离线演示版

`Sourcing-Committee-Cockpit-demo-<日期>.html`：把驾驶舱页面和当时演示库的数据打包成一个文件，没有服务器也能双击打开给人看。所有页面可点；提交、审批、编辑等写操作会提示"只读演示副本"，不会保存。页面以演示管理员 "Demo Viewer" 身份打开，所以管理员才有的按钮（编辑、Accounts、系统设置）都能看到。

重新生成（8062 演示服务在跑时）：

```bash
cd backend
uv run python scripts/build_demo_page.py --out "../.design/demo/Sourcing-Committee-Cockpit-demo-$(date +%F).html" \
  --exclude-swat SWAT-9900 SWAT-99001 --exclude-sub SUB-0002 SUB-0003
```

`--exclude-*` 去掉演示库里的测试残留；`--snapshot` 可改用保存好的 `/api/bootstrap` JSON。这是展示材料，不是实现参考。
