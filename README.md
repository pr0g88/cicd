# 🚀 CI/CD Templates Repository — PizzaShop

Централизованный репозиторий шаблонов CI/CD и оркестратор релизов для микросервисной архитектуры проекта **PizzaShop**.

Обеспечивает единые стандарты безопасности, тестирования, сборки и деплоя для всех **9 микросервисов**, написанных на **5 языках программирования** (Go, Java, Node.js, Python, Rust).

---

## 📋 Содержание

- [Архитектура проекта](#-архитектура-проекта)
- [Структура репозитория](#-структура-репозитория)
- [Этапы пайплайна](#-этапы-пайплайна-pipeline-stages)
- [Тегирование Docker-образов](#-тегирование-docker-образов)
- [Оркестратор релизов](#-оркестратор-релизов)
- [Подключение к микросервису](#-подключение-к-микросервису)
- [Безопасность и Best Practices](#-безопасность-и-best-practices)
- [Переменные окружения](#-переменные-окружения)
- [Поддержка и развитие](#-поддержка-и-развитие)

---

## 🏗️ Архитектура проекта

Проект **PizzaShop** — это система доставки пиццы, построенная на микросервисной архитектуре с асинхронной коммуникацией через **RabbitMQ** и синхронными HTTP-вызовами.

| Сервис | Язык | Фреймворк | Описание |
|:---|:---|:---|:---|
| `catalog-service` | Go | Gorilla Mux, sqlx | Каталог пицц и ингредиентов |
| `kitchen-service` | Go | Gorilla Mux, sqlx | Управление кухней и заказами |
| `inventory-service` | Go | Gorilla Mux, sqlx | Управление складом и остатками |
| `order-service` | Java | Spring Boot, Maven | Создание и управление заказами |
| `payment-service` | Java | Spring Boot, Gradle | Обработка платежей и валидация карт |
| `notification-service` | Node.js | Express | Уведомления (email, push, SMS) |
| `delivery-service` | Python | FastAPI | Управление доставкой |
| `auth-service` | Rust | Actix-Web, SQLx | Аутентификация и JWT-токены |
| `user-service` | Rust | Actix-Web, SQLx | Управление профилями пользователей |

Помимо девяти микросервисов, в состав приложения также входят `api-gateway` (единая точка входа для внешних запросов) и `frontend` (веб-клиент). Они собираются и деплоятся по тем же принципам, что и остальные сервисы, но не входят в число "9 микросервисов" бизнес-логики.

**Общие технологии:** PostgreSQL 15+, RabbitMQ 3.11+, HashiCorp Vault, Kubernetes, Helm, Helmfile, Docker.

---

## 📂 Структура репозитория

```text
cicd/
├── README.md                         # Этот файл
├── .gitlab-ci.yml                    # Оркестратор релизов (запуск всех сервисов)
├── variables/                        # Глобальные переменные для всех пайплайнов
│   └── .job-vars.gitlab-ci.yml
├── rules/                            # Переиспользуемые правила (YAML-якоря)
│   └── .job-rules.gitlab-ci.yml
└── templates/                        # Шаблоны этапов пайплайна
    ├── common/                       # 🔹 Универсальные шаблоны (для любого языка)
    │   ├── .sast-template.gitlab-ci.yml          # Semgrep
    │   ├── .sca-template.gitlab-ci.yml           # Trivy FS
    │   ├── .secret-scan-template.gitlab-ci.yml   # Gitleaks
    │   ├── .docker-build-template.gitlab-ci.yml  # Docker Build + Push
    │   ├── .container-scan-template.gitlab-ci.yml # Trivy Image
    │   ├── .helm-deploy-template.gitlab-ci.yml   # Helm Deploy
    │   └── .rollback-template.gitlab-ci.yml      # Helm Rollback
    ├── go/                           # 🔹 Go (только unit-тесты)
    │   └── .go-unit-test-template.gitlab-ci.yml
    ├── java/                         # 🔹 Java (Maven / Gradle unit-тесты)
    │   ├── .java-maven-unit-test-template.gitlab-ci.yml
    │   └── .java-gradle-unit-test-template.gitlab-ci.yml
    ├── nodejs/                       # 🔹 Node.js (Jest unit-тесты)
    │   └── .nodejs-unit-test-template.gitlab-ci.yml
    ├── python/                       # 🔹 Python (pytest unit-тесты)
    │   └── .python-unit-test-template.gitlab-ci.yml
    └── rust/                         # 🔹 Rust (cargo test + grcov)
        └── .rust-unit-test-template.gitlab-ci.yml
```

---

## 🔄 Этапы пайплайна (Pipeline Stages)

В проекте два уровня пайплайнов, которые не пересекаются напрямую, но связаны общими шаблонами и единым тегом образа.

### 1. Пайплайн сервиса (в репозитории каждого микросервиса)

Каждый из 9 сервисов + `api-gateway` + `frontend` подключает шаблоны из `templates/` через `include:` и запускает их на MR и push в ветки `dev` / `staging` / `main` (правила берутся из `rules/.job-rules.gitlab-ci.yml`):

| Стадия | Шаблон | Инструмент | Блокирует пайплайн |
|:---|:---|:---|:---|
| `secret-scan` | `.secret-scan-template.gitlab-ci.yml` | Gitleaks | ✅ да |
| `sast` | `.sast-template.gitlab-ci.yml` | Semgrep | ⚠️ нет (только отчёт) |
| `sca` | `.sca-template.gitlab-ci.yml` | Trivy (filesystem) | ✅ да, если уязвимость чинится |
| `unit-test` | `<lang>/.{go,java,nodejs,python,rust}-unit-test-template.gitlab-ci.yml` | go test / JUnit+Jacoco / Jest / pytest / cargo test | ✅ да, при недостаточном покрытии |
| `build` | `.docker-build-template.gitlab-ci.yml` | Docker Build + Push | ✅ да |
| `container-scan` | `.container-scan-template.gitlab-ci.yml` | Trivy (image) | ⚠️ нет (`allow_failure: true`, только отчёт) |
| `deploy` | `.helm-deploy-template.gitlab-ci.yml` | Helm upgrade --install | по правилам `.rules:deploy-*` |
| `rollback` | `.rollback-template.gitlab-ci.yml` | Helm rollback | ручной запуск |

Минимальный порог покрытия юнит-тестами (`MIN_COVERAGE_UNIT`) — **30%** для Go/Java/Node.js/Python и **4%** для Rust (ниже из-за особенностей измерения покрытия через `grcov` на раннем этапе проекта).

### 2. Пайплайн-оркестратор (этот репозиторий, `.gitlab-ci.yml`)

Запускается **только** на Git-теге вида `vX.Y.Z` и фиксирует релиз сразу по всем сервисам:

```
.pre → build → deploy → post-deploy-tests → dast → deploy-prod → rollback
```

| Стадия | Джобы |
|:---|:---|
| `.pre` | `generate-image-tag`, `tag-service-repos`, `create-release`, `release-notify` |
| `build` | `trigger-frontend`, `trigger-api-gateway`, `trigger-<service>` (×9) |
| `deploy` | `deploy-dev` → `e2e-smoke-dev` (дымовой Playwright по dev, `allow_failure: true`) → `deploy-staging` → `staging-ready-notify` |
| `post-deploy-tests` | `e2e-staging` — полный набор сценариев Playwright против staging |
| `dast` | `dast-frontend`, `dast-api-gateway` (OWASP ZAP по живому staging), `prod-approval-notify` |
| `deploy-prod` | `dry-run-prod` (запускается сам) → `deploy-prod` (manual, заглушка) → `prod-deployed-notify` |
| `rollback` | `rollback-dev`, `rollback-staging` (manual), `rollback-prod` (manual, заглушка) |

`*-notify` джобы шлют короткие статусы пайплайна в Telegram (`templates/common/.send-notification-template.gitlab-ci.yml`) и не влияют на результат пайплайна — все с `allow_failure: true`.

---

## 🏷️ Тегирование Docker-образов

Каждый релиз получает единый (unified) тег образа, одинаковый для всех сервисов:

```
UNIFIED_IMAGE_TAG = ${CI_COMMIT_TAG}-${CI_COMMIT_SHORT_SHA}
```

Тег вычисляется один раз в джобе `generate-image-tag` и прокидывается во все триггерные пайплайны сервисов через `artifacts: reports: dotenv` + `trigger: forward: yaml_variables: true`. Это гарантирует, что все 9 сервисов + `api-gateway` + `frontend` в рамках одного релиза деплоятся строго одной и той же версией образов, независимо от того, что происходит в их ветках `main` дальше.

Если пайплайн сервиса запускается **не** из оркестратора (обычный push/MR, без релизного тега), шаблоны `.docker-build-template` и `.helm-deploy-template` используют локальный фолбэк-тег — `${CI_PIPELINE_ID}`.

---

## 🚀 Оркестратор релизов

Ветки — по GitLab Flow (environment branches): `dev` → `staging` → `main`,
каждая автодеплоится в своё окружение при пуше (см. `rules/.job-rules.gitlab-ci.yml`).
`main` — единственная ветка, с которой можно резать релиз, поэтому перед тегом
нужен смёрженный MR `staging → main`.

Флоу запускается созданием Git-тега `vX.Y.Z` в этом репозитории (`cicd`) на HEAD ветки `main`:

1. **`generate-image-tag`** — вычисляет `UNIFIED_IMAGE_TAG`.
2. **`tag-service-repos`** — ставит тег `vX.Y.Z` в каждом из 9 репозиториев сервисов и в репозитории `frontend` (на HEAD ветки `main`), фиксируя точный набор коммитов релиза. Идемпотентно: повторный запуск с уже существующим тегом не фейлится, а переиспользует его.
3. **`create-release`** — создаёт GitLab Release с описанием релиза и таблицей коммитов (SHA) каждого сервиса.
4. **`trigger-*`** — параллельно триггерит сборку всех 9 сервисов + `api-gateway` + `frontend` строго по только что созданному тегу (`branch: $CI_COMMIT_TAG`), а не по текущему состоянию `main`.
5. **`deploy-dev` → `deploy-staging`** — деплой через `helmfile apply` единым тегом образа (`--state-values-set image.tag=${IMAGE_TAG}`), с `resource_group` на каждое окружение, чтобы исключить параллельные деплои в одно и то же окружение. Между ними — дымовой e2e-прогон по dev, после — полный e2e и DAST по staging.
6. **`deploy-prod`** — **заглушка**. Ручной джоб (`when: manual`), реального деплоя не выполняет — демонстрирует protected environment + manual approval gate, которые использовались бы в реальном продакшене.

### Откат (rollback)

`rollback-dev` / `rollback-staging` запускаются вручную и поддерживают два режима:

- **Без указания `IMAGE_TAG`** — откат каждого релиза на предыдущую Helm-ревизию (`helm rollback`) по всем сервисам сразу.
- **С указанием `IMAGE_TAG`** — целевой откат на конкретную версию через `helmfile apply --state-values-set image.tag=${IMAGE_TAG}`.

Отдельно, на уровне отдельного сервиса, `.rollback-template.gitlab-ci.yml` в `templates/common/` реализует более точный откат: вычисляет именно последнюю успешную ревизию (`description == "Upgrade complete"`) через `helm history`, а не просто "на одну ревизию назад".

---

## 🔌 Подключение к микросервису

Чтобы подключить новый сервис к общим шаблонам, в его `.gitlab-ci.yml` нужно сделать `include` файлов из этого репозитория и `extends` нужных джобов. Пример для Go-сервиса:

```yaml
include:
  - project: 'cluster-application/cicd'
    ref: main                                              # или tpl-vX.Y.Z для фиксированной версии шаблонов
    file:
      - '/variables/.job-vars.gitlab-ci.yml'
      - '/rules/.job-rules.gitlab-ci.yml'
      - '/templates/common/.secret-scan-template.gitlab-ci.yml'
      - '/templates/common/.sast-template.gitlab-ci.yml'
      - '/templates/common/.sca-template.gitlab-ci.yml'
      - '/templates/go/.go-unit-test-template.gitlab-ci.yml'
      - '/templates/common/.docker-build-template.gitlab-ci.yml'
      - '/templates/common/.container-scan-template.gitlab-ci.yml'
      - '/templates/common/.helm-deploy-template.gitlab-ci.yml'
      - '/templates/common/.rollback-template.gitlab-ci.yml'

stages:
  - secret-scan
  - sast
  - sca
  - unit-test
  - build
  - container-scan
  - deploy
  - rollback

variables:
  SERVICE_DIR: "catalog-service"      # используется во всех шаблонах: путь в registry, helm-чарт, git clone
  SEMGREP_CONFIG: "p/golang"          # переопределяет дефолтный p/auto под язык сервиса
  NAMESPACE: "pizzashop-${ENVIRONMENT_NAME}"

secret-scan:
  extends: .template:secret-scan

sast:
  extends: .template:sast

sca:
  extends: .template:sca

unit-test:
  extends:
    - .template:go-unit-test
    - .rules:test

build:
  extends:
    - .template:docker-build
    - .rules:build

container-scan:
  extends: .template:container-scan

deploy-dev:
  extends:
    - .template:helm-deploy
    - .rules:deploy-dev

deploy-staging:
  extends:
    - .template:helm-deploy
    - .rules:deploy-staging

rollback:
  extends: .template:rollback
```

Единственное, что обязательно для каждого сервиса, — переменная **`SERVICE_DIR`** (имя папки/чарта/образа сервиса) и, при необходимости, **`SEMGREP_CONFIG`** под конкретный язык (`p/golang`, `p/java`, `p/nodejs`, `p/python`, `p/rust`).

---

## 🔐 Безопасность и Best Practices

- **Секреты не хранятся в репозиториях.** Все чувствительные данные (пароли БД, ключи RabbitMQ, JWT-секреты) подтягиваются на лету через HashiCorp Vault Agent Injector прямо в поды — ни в Helm `values.yaml`, ни в CI-переменных секретов в открытом виде нет.
- **Многослойный security-скан на уровне каждого сервиса:** секреты (Gitleaks) → статический анализ кода (Semgrep) → зависимости (Trivy SCA) → собранный образ (Trivy image scan) → после деплоя ещё и живой staging (OWASP ZAP DAST).
- **SCA не валит пайплайн на непочинимом.** `.sca-template` гоняет Trivy с `--ignore-unfixed` (не блокирует на уязвимостях без патча) и подхватывает `.trivyignore` в корне сервиса — туда можно вписать CVE-ID принятого риска с доступным фиксом.
- **Минимальный порог покрытия тестами** проверяется автоматически (`MIN_COVERAGE_UNIT`) и блокирует сборку при недостаточном покрытии.
- **Идемпотентное тегирование релизов** — повторный запуск релизного пайплайна с уже существующим тегом не ломает состояние сервисных репозиториев.
- **Protected environments + manual gate** — деплой в prod вынесен в отдельный ручной джоб с `environment: prod`, что в реальном GitLab-проекте сочетается с protected environment и списком approvers.
- **`resource_group`** на джобах деплоя исключает одновременные конкурирующие деплои в одно окружение.
- **Доступ к Helm-репозиторию** — по выделенному deploy-токену (`GROUP_DEPLOY_TOKEN_USERNAME` / `GROUP_DEPLOY_TOKEN_PASSWORD`), а не по личным учётным данным.

---

## ⚙️ Переменные окружения

Инфраструктурные хосты (внутренний registry, NodePort ingress-controller'а,
публичный домен) не хардкодятся в YAML — задаются CI/CD-переменными на
уровне группы `cluster-application` (Settings → CI/CD → Variables), чтобы
поменять их можно было в одном месте, а не в полусотне файлов по всем репо.

| Переменная | Что это | Пример значения |
|:---|:---|:---|
| `INFRA_REGISTRY` | Внутренний Docker registry (host:port) — используется во всех `image:` и как `image.registry` в Helm-чартах | `-` |
| `INFRA_CLUSTER_IP` | NodePort IP ingress-controller'а — нужен только DAST-джобам (`dast-frontend`, `dast-api-gateway`), которые бьют по живому staging напрямую по IP:порту | `-` |
| `PUBLIC_DOMAIN` | Публичный домен, через который проксируются dev/staging и GitLab API | `-` |

Все три — обычные (не Protected, не Masked) переменные: это не секреты, а
инфраструктурные адреса, и они нужны в пайплайнах на любых ветках, включая
MR из форков и feature-веток. Protected-переменная на непротектед-ветке
просто не будет видна джобу — сборка/деплой сломается с пустым хостом.

Group-переменная видна всем проектам группы — задать её нужно один раз,
и `cicd`, `e2e-tests`, `infrastructure`, а через шаблоны `include:` — и
все сервисные репозитории, подхватят её автоматически.

`INFRA_REGISTRY` также нужен деплою через Helm/Helmfile: `values.yaml`
чартов не имеет доступа к CI-переменным напрямую, поэтому `image.registry`
там всегда пустой (`""`) и подставляется явно через `--set image.registry=`
(`.helm-deploy-template.gitlab-ci.yml`) или `--state-values-set image.registry=`
(оркестраторные `helmfile apply`) — см. `helm/README.md`.

---

## 🛠️ Поддержка и развитие

Шаблоны версионируются тегами `tpl-vX.Y.Z` (не путать с релизными тегами `vX.Y.Z`, которые запускают оркестратор) — сервисы могут закрепиться на конкретной версии шаблонов через `ref:` в `include:`, чтобы обновление этого репозитория не ломало их пайплайны без явного апгрейда.

Изменения в шаблоны и оркестратор вносятся через Merge Request в этот репозиторий; после мержа в `main` рекомендуется поставить новый `tpl-vX.Y.Z` тег для потребителей, которые хотят зафиксироваться на стабильной версии.

**Известные ограничения:**

- Деплой в `prod` — демонстрационная заглушка (проект учебный, реального prod-окружения нет).
- `sast` и `container-scan` сейчас не блокируют пайплайн (только репортят находки) — в реальном проде их стоило бы сделать блокирующими хотя бы для критичных уязвимостей.
- Планируется вынести общие Kubernetes-манифесты Helm-чартов в library chart, чтобы не дублировать `deployment.yaml` / `service.yaml` в каждом из 11 чартов.
