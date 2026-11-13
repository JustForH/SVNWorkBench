# -*- coding: utf-8 -*-
"""SVNWorkBench 桌面版（svnwb 包）。

模块划分（按功能拆分，避免循环导入）：
  core         平台常量、排除规则与通用工具、界面文案/配色常量（不依赖 tkinter）
  config_store 配置持久化：单文件 _settings.json（默认 ~/.config/SVNWorkBench/）
  runner       后台执行 svn 命令的线程（凭据/证书重试、日志落盘）
  hub          服务层：单任务调度 + 事件队列（界面轮询取用）
  dialogs      通用弹窗与界面辅助（确认框/认证/证书/日志窗口/输入快捷键）
  app          主窗口（工作副本页）与程序入口 main()
  repo_browser 仓库浏览器 + 检出/更新勾选对话框（主界面懒加载）
  log_view     提交历史窗口（svn log + 版本对比，主界面懒加载）

入口脚本 SVNWorkBench.py 只是薄壳：import 本包并调用 app.main()。
"""
