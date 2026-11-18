/* =====================================================================
 * 接口适配 · 技能中心（界面只调这里）。路径与《接口规范》§技能 同名同构。
 * 真实后端：haiknow builder（需求包 → 渲染 → 预检 → 发布）+ reviews（上架审核）+ jobs（运行）。
 * 实体 Skill = { id, name, icon, summary, author, authorId, dept, version, versions[], status: draft|published|in_review|rejected,
 *               share:{scope:private|people|dept|zone, people[], perm:view|use|edit}, uses, rating, ratingN, forks, source, promote,
 *               spec: SkillSpec }   SkillSpec 见 apps/skills/README.md
 * ===================================================================== */
(function () {
  const H = window.JKHttp; window.JKApi = window.JKApi || {};
  window.JKApi.skills = Object.assign(window.JKApi.skills || {}, {
    /** {mine?, review?} → {items: Skill[], apps: App[]}（只返回当前用户可见的） */ list: (q) => H.get('/api/v1/skills', q),
    /** id → {item: Skill, runs: SkillRun[]} */ get: (id) => H.get('/api/v1/skills/' + id),
    /** → {models, spaces, tools, computerTasks, users, myDept} 编辑器下拉选项 */ options: () => H.get('/api/v1/skills/meta/options'),
    /** {text} → {draft: {name, icon, summary, base, spec, questions[]}}  AI 用一句话起草 */ draft: (text) => H.post('/api/v1/skills/draft', { text }),
    /** {name, summary, icon, base, spec, forkOf?} → {item}  新建草稿 */ create: (b) => H.post('/api/v1/skills', b),
    /** {name?, summary?, spec?, note?} → {item}  已发布的保存为新版本 */ save: (id, b) => H.patch('/api/v1/skills/' + id, b),
    /** {share:{scope,people,perm}} → {item, review|null}  全区公开会生成上架审核 */ publish: (id, share) => H.post(`/api/v1/skills/${id}/publish`, { share }),
    /** {scope, people, perm} → {item, review|null} */ share: (id, b) => H.post(`/api/v1/skills/${id}/share`, b),
    /** {decision:'approve'|'reject', reason} → {item}  管理员 / 审签领导 */ review: (id, b) => H.post(`/api/v1/skills/${id}/review`, b),
    /** → {item}  复制改一改 */ fork: (id) => H.post(`/api/v1/skills/${id}/fork`, {}),
    /** {v} → {item}  回到某个版本（生成新版本） */ restore: (id, v) => H.post(`/api/v1/skills/${id}/restore`, { v }),
    /** → {ok, item} */ remove: (id) => H.del('/api/v1/skills/' + id),
    /** {item} → {ok}  撤销删除 */ undoRemove: (item) => H.post(`/api/v1/skills/${item.id}/restore-deleted`, { item }),
    /** {useful:boolean} → {item} */ rate: (id, useful) => H.post(`/api/v1/skills/${id}/rate`, { useful }),
    /** {inputs} → {job: SkillJob}  运行（长任务） */ run: (id, inputs) => H.post(`/api/v1/skills/${id}/run`, { inputs }),
    /** {skill:{name,spec}, inputs} → {job}  试运行未保存的草稿 */ trial: (skill, inputs) => H.post('/api/v1/skills/trial', { skill, inputs }),
    /** → {job: {id, status: running|done|failed, steps:[{label,type,status}], result:{title, markdown, citations[], missing[], model, computer}}} */ job: (jobId) => H.get('/api/v1/skills/jobs/' + jobId),
    /** {text} → {skill|null, score}  对话里按触发语找技能 */ match: (text) => H.post('/api/v1/skills/match', { text }),
    /** → {appJson, skillMd}  升级为小应用时生成的小应用 app.json 与 SKILL.md */ manifest: (id) => H.get(`/api/v1/skills/${id}/manifest`),
    /** {appId} → {item}  提交开发组（走 MR 门禁） */ promote: (id, appId) => H.post(`/api/v1/skills/${id}/promote`, { appId }),
  });
})();
