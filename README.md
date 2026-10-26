# virtual-shipyard-simulator

## 브랜치 전략

- `main`: 배포/안정 브랜치
- `develop`: 개발 통합 브랜치. 작업 브랜치는 `develop`에서 분기하여 PR로 병합
- `develop` 대상 PR은 GitHub Actions로 자동 머지, `main` 머지는 수동
- 버전은 `main`에 `vX.Y.Z` 태그로 관리 (현재 `v0.0.1`)
