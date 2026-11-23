"""数据库项目目录与实时成员范围查询。"""
from haiknow_sdk import DataError


class Projects:
    def __init__(self, directory):
        self.directory = directory

    @property
    def by_id(self):
        return self.directory.projects()

    @property
    def companies(self):
        return self.directory.companies()

    def visible(self, user, project: str) -> bool:
        scope = self.directory.project_ids(user.id)
        return project in self.by_id and ('*' in scope or project in scope)

    def require(self, user, project: str) -> dict:
        if not self.visible(user, project):
            raise DataError('not_found', '项目或资源不存在')
        return self.by_id[project]

    def tree(self, user) -> dict:
        companies = []
        for company in self.companies:
            projects = [p for p in company['projects'] if self.visible(user, p['id'])]
            if projects:
                companies.append({**company, 'projects': projects})
        return {'companies': companies}
