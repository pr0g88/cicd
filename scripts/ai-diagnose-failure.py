#!/usr/bin/env python3
"""
Диагностика упавшей джобы пайплайна через Kimi (moonshotai/kimi-k2.6, ProxyAPI)
с отправкой результата в Telegram-bot, что и .send-notification-template.
Запускается отдельной джобой в оркестраторе с rules: - when: on_failure .
"""

import os
import re
import sys
import time
import uuid

import requests
from openai import OpenAI

MAX_LOG_CHARS = 12000       # сколько символов хвоста лога отдаём модели (~3-4К токенов)
MAX_DIAGNOSIS_TOKENS = 400  # ограничиваем ответ, чтобы не разгонять счёт

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def env_or_exit(name):
    value = os.environ.get(name)
    if not value:
        print(f"⚠️  {name} не задан — пропускаю диагностику", file=sys.stderr)
        sys.exit(0)
    return value


def gitlab_api_get(url, token):
    headers = {"PRIVATE-TOKEN": token} if token else {}
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp


def find_failed_jobs(api_url, project_id, pipeline_id, token):
    url = f"{api_url}/projects/{project_id}/pipelines/{pipeline_id}/jobs?per_page=100"
    jobs = gitlab_api_get(url, token).json()
    failed = [j for j in jobs if j.get("status") == "failed"]
    for j in failed:
        j["_kind"] = "job"
    return failed


def find_failed_bridges(api_url, project_id, pipeline_id, token):
    # trigger-*-service — это bridge-джобы (multi-project trigger), а не обычные
    # джобы. GitLab не отдаёт их через /pipelines/:id/jobs — только через
    # отдельный эндпоинт /pipelines/:id/bridges. Именно тут раньше "терялась"
    # ошибка "Missing CI config file": сам bridge падает, а find_failed_jobs()
    # его не видел.
    # ВАЖНО: в отличие от обычных джоб, у bridge-джобы НЕТ обычного трейса —
    # GET /jobs/:id/trace для её id отдаёт 404 (проверено на этом GitLab).
    # Зато вся нужная диагностика уже есть прямо в самом JSON-объекте бриджа:
    # failure_reason и (если он вообще создался) downstream_pipeline — см.
    # bridge_diagnostic_text() ниже, используется вместо fetch_trace().
    url = f"{api_url}/projects/{project_id}/pipelines/{pipeline_id}/bridges?per_page=100"
    bridges = gitlab_api_get(url, token).json()
    failed = [b for b in bridges if b.get("status") == "failed"]
    for b in failed:
        b["_kind"] = "bridge"
    return failed


def bridge_diagnostic_text(bridge):
    """Собирает 'псевдо-трейс' из полей самого bridge-объекта — trace для
    bridge-джоб GitLab не отдаёт, но failure_reason обычно и так содержит
    суть (например downstream_pipeline_creation_failed — как раз случай
    "Missing CI config file")."""
    lines = [
        f"Bridge-джоба «{bridge.get('name')}» (id={bridge.get('id')}) "
        f"завершилась со статусом failed."
    ]
    reason = bridge.get("failure_reason")
    if reason:
        lines.append(f"failure_reason: {reason}")
    downstream = bridge.get("downstream_pipeline")
    if downstream:
        lines.append(
            f"downstream_pipeline: id={downstream.get('id')}, "
            f"status={downstream.get('status')}, url={downstream.get('web_url')}"
        )
    else:
        lines.append(
            "downstream_pipeline не создан вообще — ошибка произошла ещё до "
            "старта дочернего пайплайна (типичная причина: в целевом "
            "репозитории/ветке нет .gitlab-ci.yml или он невалиден)."
        )
    return "\n".join(lines)


def find_failed_downstream_job(api_url, downstream_project_id, downstream_pipeline_id, token):
    # Токену (GITLAB_API_TOKEN) для этого нужен read_api проекта
    url = f"{api_url}/projects/{downstream_project_id}/pipelines/{downstream_pipeline_id}/jobs?per_page=100"
    jobs = gitlab_api_get(url, token).json()
    failed = [j for j in jobs if j.get("status") == "failed"]
    return failed[0] if failed else None


def fetch_trace(api_url, project_id, job_id, token):
    url = f"{api_url}/projects/{project_id}/jobs/{job_id}/trace"
    trace = gitlab_api_get(url, token).text
    trace = ANSI_RE.sub("", trace)
    return trace[-MAX_LOG_CHARS:]


def ask_kimi(job_name, trace):
    client = OpenAI(
        api_key=env_or_exit("PROXYAPI_KEY"),
        base_url="https://api.proxyapi.ru/v1",
    )
    system_prompt = (
        "Ты — опытный DevOps-инженер в команде, разбираешь упавшую джобу GitLab CI. "
        "Пиши по-русски, коротко (3-5 предложений), как коллега в чат, без markdown-заголовков "
        "и списков. Назови вероятную причину падения и что конкретно проверить или поправить. "
        "Если по логу причина не очевидна — так и скажи, не выдумывай."
    )
    user_prompt = f"Упала джоба «{job_name}». Хвост лога:\n\n{trace}"

    completion = client.chat.completions.create(
        model="moonshotai/kimi-k2.6",
        max_tokens=MAX_DIAGNOSIS_TOKENS,
        temperature=0.3,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return completion.choices[0].message.content.strip()


def send_to_telegram_relay(text):
    tg_url = env_or_exit("TG_NOTIFY_URL")
    tg_key = env_or_exit("TG_NOTIFY_API_KEY")
    chat_id = os.environ.get("TG_NOTIFY_CHAT_ID")
    ca_cert = os.environ.get("TG_NOTIFY_CA_CERT")

    payload = {"text": text}
    if chat_id:
        payload["chat_id"] = chat_id

    job_name = os.environ.get("CI_JOB_NAME", "ai-diagnose-failure")
    pipeline_id = os.environ.get("CI_PIPELINE_ID", str(uuid.uuid4()))
    idempotency_key = f"{job_name}-{pipeline_id}"

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": tg_key,
        "Idempotency-Key": idempotency_key,
    }
    verify = ca_cert if (ca_cert and os.path.isfile(ca_cert)) else True

    for attempt in range(1, 11):
        try:
            resp = requests.post(tg_url, json=payload, headers=headers, timeout=20, verify=verify)
            if resp.status_code == 200:
                print(f"✅ диагноз отправлен (Idempotency-Key: {idempotency_key})")
                return
            print(f"❌ HTTP {resp.status_code}, попытка {attempt}/10: {resp.text}", file=sys.stderr)
        except requests.RequestException as exc:
            print(f"❌ сетевая ошибка, попытка {attempt}/10: {exc}", file=sys.stderr)
        time.sleep(3)

    print("⚠️  не удалось отправить диагноз после 10 попыток — сдаюсь молча", file=sys.stderr)


def main():
    api_url = os.environ.get("CI_API_V4_URL", "").rstrip("/")
    project_id = os.environ.get("CI_PROJECT_ID")
    pipeline_id = os.environ.get("CI_PIPELINE_ID")
    pipeline_url = os.environ.get("CI_PIPELINE_URL", "")
    # CI_JOB_TOKEN далеко не всегда имеет права читать джобы/логи другой джобы
    # в том же проекте (зависит от версии GitLab и настроек scope) — надёжнее
    # завести отдельный Project/Group Access Token с read_api и положить его
    # в GITLAB_API_TOKEN. Если его нет — пробуем CI_JOB_TOKEN как фолбэк.
    gitlab_token = os.environ.get("GITLAB_API_TOKEN") or os.environ.get("CI_JOB_TOKEN")

    if not (api_url and project_id and pipeline_id):
        print("⚠️  нет CI_API_V4_URL/CI_PROJECT_ID/CI_PIPELINE_ID — похоже, не в CI", file=sys.stderr)
        sys.exit(0)

    # Собираем падения из двух разных источников: обычные джобы и bridge-джобы
    # (trigger-*-service и т.п.). Если один эндпоинт недоступен — не сдаёмся
    # сразу, пробуем второй; молчим полностью только если оба пусты/недоступны.
    failed = []

    try:
        failed.extend(find_failed_jobs(api_url, project_id, pipeline_id, gitlab_token))
    except requests.RequestException as exc:
        print(f"⚠️  не смог получить список джоб пайплайна: {exc}", file=sys.stderr)

    try:
        failed.extend(find_failed_bridges(api_url, project_id, pipeline_id, gitlab_token))
    except requests.RequestException as exc:
        print(f"⚠️  не смог получить список bridge-джоб (trigger-*) пайплайна: {exc}", file=sys.stderr)

    if not failed:
        print("пайплайн упал, но упавших джоб через API не нашёл — пропускаю")
        sys.exit(0)

    # Если упало несколько джоб сразу — разбираем первую, чтобы не слать
    # несколько сообщений подряд; остальные просто перечисляем по именам.
    target = failed[0]
    others = [j["name"] for j in failed[1:]]

    if target.get("_kind") == "bridge":
        trace = None
        downstream = target.get("downstream_pipeline") or {}
        ds_project_id = downstream.get("project_id")
        ds_pipeline_id = downstream.get("id")
        if ds_project_id and ds_pipeline_id:
            try:
                downstream_job = find_failed_downstream_job(
                    api_url, ds_project_id, ds_pipeline_id, gitlab_token
                )
                if downstream_job:
                    downstream_trace = fetch_trace(
                        api_url, ds_project_id, downstream_job["id"], gitlab_token
                    )
                    trace = (
                        f"Реальная упавшая джоба в дочернем пайплайне: "
                        f"«{downstream_job['name']}» (проект {ds_project_id}, "
                        f"пайплайн {ds_pipeline_id}).\n\nХвост её лога:\n\n{downstream_trace}"
                    )
            except requests.RequestException as exc:
                print(
                    f"⚠️  не смог дотянуться до дочернего пайплайна {ds_pipeline_id} "
                    f"в проекте {ds_project_id}: {exc} — похоже, GITLAB_API_TOKEN "
                    "не хватает прав (нужен read_api на всю группу, а не только на cicd)",
                    file=sys.stderr,
                )
        if trace is None:
            trace = bridge_diagnostic_text(target)
    else:
        try:
            trace = fetch_trace(api_url, project_id, target["id"], gitlab_token)
        except requests.RequestException as exc:
            print(f"⚠️  не смог получить лог джобы {target['name']}: {exc}", file=sys.stderr)
            trace = "(лог получить не удалось)"

    try:
        diagnosis = ask_kimi(target["name"], trace)
    except Exception as exc:  # не хотим падать из-за проблем на стороне провайдера модели
        print(f"⚠️  Kimi не ответил: {exc}", file=sys.stderr)
        diagnosis = "не смог получить диагноз от модели, смотрите лог руками"

    header = f"🔴 Упала джоба «{target['name']}»"
    if others:
        header += f" (и ещё {len(others)}: {', '.join(others)})"

    text = f"{header}\n\n{diagnosis}\n\n{pipeline_url}"
    send_to_telegram_relay(text)


if __name__ == "__main__":
    main()
