/* =====================================================================
 * 【可改】一键演示脚本：按顺序执行。每一步可用：
 *   { caption:'顶部字幕' }        { login:'wangmin' }（切换演示账号）
 *   { say:'一句话' }              AI 理解后在右侧替你操作（遇到确认自动选第一个）
 *   { file:'样例文件id' }         模拟把文件拖进对话框（见 config/sample-files.js）
 *   { appDemo:'policy' }          运行该应用 manifest.demo 里写好的片段
 *   { open:'inbox'|'admin', tab } 打开平台面板       { theme:'light'|'dark' }
 *   { click:'[data-op=...]' }     点界面上的某个按钮   { wait:毫秒 }  { newChat:true }
 * ===================================================================== */
window.JK_DEMO_SCRIPT = [
  { title: '开场', steps: [{ login: 'wangmin' }, { caption: '这是经办人员王敏的工作台：一个对话框，说一句话 AI 就替你办' }, { wait: 1800 }] },
  { title: '政策兑现', steps: [{ caption: '① 政策兑现：说出企业名，AI 逐项核对政策' }, { newChat: true }, { appDemo: 'policy' }] },
  { title: '企业走访', steps: [{ caption: '② 企业管理：一企一档、走访记录 AI 整理成台账建议，人确认后才写入' }, { newChat: true }, { appDemo: 'enterprise' }] },
  { title: '会议纪要', steps: [{ caption: '③ 会议记录：拖入录音，自动转写、分发言人、出纪要和待办' }, { newChat: true }, { file: 'rec-1117' }, { appDemo: 'meeting', skipFirst: true }] },
  { title: '公文协作', steps: [{ caption: '④ 公文协作：丢进草稿，按范文起草、核查后送审，再看版本比对' }, { newChat: true }, { file: 'draft-shujuquan' }, { say: '起草一份数据券申报延期通知' }, { say: '送审签' }, { say: '打开书香里的答复意见，对比一下第1版和第2版' }] },
  { title: '知识库', steps: [{ caption: '⑤ 知识库：提问直接给出处，点开就是政策原文' }, { newChat: true }, { appDemo: 'kb' }] },
  { title: '技能中心', steps: [{ caption: '⑥ 技能中心：把常用做法做成技能，分享给同事' }, { newChat: true }, { appDemo: 'skills' }] },
  { title: '电脑操作', steps: [{ caption: '⑦ 电脑操作：AI 替你去其它系统填报，提交前停下等你确认' }, { newChat: true }, { appDemo: 'computer' }] },
  { title: '审签', steps: [{ caption: '⑧ 换成审签领导李阳：刚送审的通知在收件箱里，一键通过' }, { login: 'liyang' }, { open: 'inbox' }, { wait: 1600 }, { click: '[data-op^="inbox.approve."]' }, { wait: 1200 }] },
  { title: '外部协作者', steps: [{ caption: '⑨ 外部协作者何军：只看授权应用，电话营收自动打码' }, { login: 'hejun' }, { wait: 1200 }, { say: '查一下星河智驾' }, { wait: 1500 }] },
  { title: '管理后台', steps: [{ caption: '⑩ 管理员：账号、授权、模型、审计，改动立即生效' }, { login: 'admin' }, { open: 'admin', tab: 'grants' }, { wait: 1800 }, { open: 'admin', tab: 'models' }, { wait: 1400 }, { open: 'admin', tab: 'audit' }, { wait: 1600 }] },
  { title: '浅色主题', steps: [{ caption: '深色、浅色两套主题都可用' }, { theme: 'light' }, { wait: 1800 }, { theme: 'dark' }, { login: 'wangmin' }, { caption: '演示结束 · 可以随便点，右下角头像菜单可“重置演示数据”' }, { wait: 2400 }] },
];
