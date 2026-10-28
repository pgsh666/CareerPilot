"""Local Chinese normalization, bounded terminology and unchanged voice submission."""
import json
import subprocess
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from test_training import read, start, wait
from test_training import training as training

from app.config import Settings
from app.models import GenerationJob
from app.speech_service import LocalSpeech
from app.speech_text import clean_terms, decoder_options, hint_terms, normalize_transcript


def test_traditional_characters_become_simplified_without_rewriting_english_or_numbers():
    text = "另外一部分就是煤礦領域貼合度這一項指標。\nChatGPT、Claude Code、RAG、F1 = 0.82。"
    expected = "另外一部分就是煤矿领域贴合度这一项指标。\nChatGPT、Claude Code、RAG、F1 = 0.82。"
    assert normalize_transcript(text) == expected
    assert normalize_transcript(expected) == expected


def test_hint_vocabulary_uses_only_current_question_and_confirmed_material_fields():
    terms = hint_terms("你如何验证RAG结果？", {"name": "Private Candidate", "skills": "Python、F1、BLEU",
                        "projects": [{"name": "课堂项目", "content": "使用Claude Code和LangGraph"}]},
                       {"requirements": "熟悉ChatGPT、Cursor和MySQL", "inference": "UnconfirmedSecretTool"})
    assert terms[0] == "RAG"
    assert {"Python", "F1", "BLEU", "Claude Code", "LangGraph", "ChatGPT", "Cursor", "MySQL"} <= set(terms)
    assert "UnconfirmedSecretTool" not in terms and "Private Candidate" not in terms


def test_vocabulary_is_bounded_deduplicated_and_cannot_contain_prompt_instructions():
    terms = clean_terms([None, 1, "RAG", "rag", "Claude Code", "请生成标准答案", "a@b.test", "x" * 100,
                         *[f"Tool{i}" for i in range(200)]])
    assert terms.count("RAG") == 1 and "rag" not in terms
    assert len(terms) <= 32 and sum(len(word) + 2 for word in terms) <= 512
    assert all("@" not in word and "请" not in word for word in terms)
    assert hint_terms("", {"skills": "https://private.invalid/DoNotCopy user@example.test"}, {}) == []


def test_decoder_keeps_transcription_multilingual_and_does_not_supply_an_answer():
    options = decoder_options(["RAG", "F1", "ChatGPT"])
    assert options["task"] == "transcribe" and options["language"] == "zh"
    assert options["multilingual"] is True and options["beam_size"] == 5
    assert options["temperature"] == 0.0 and options["condition_on_previous_text"] is False
    assert options["hotwords"] == "RAG, F1, ChatGPT"
    assert options["vad_filter"] is True and "RAG" not in options["initial_prompt"]


def test_private_worker_receives_terms_via_stdin_not_its_command_line(monkeypatch, tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.bin").write_bytes(b"isolated-presence-check")
    settings = Settings(_env_file=None, environment="test", speech_model_directory=model)
    captured = []

    def run(command, **kwargs):
        captured.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"text": "使用RAG验证结果。", "seconds": 2,
                                "provider": "local-whisper-small-v2"}).encode())

    monkeypatch.setattr(subprocess, "run", run)
    result = LocalSpeech(settings).transcribe(tmp_path / "private.audio", terms=["RAG", "F1", "RAG"])
    command, kwargs = captured[0]
    assert "RAG" not in " ".join(command)
    assert json.loads(kwargs["input"]) == {"terms": ["RAG", "F1"]}
    assert kwargs["timeout"] == 120 and command[1] == "-I"
    assert result["text"] == "使用RAG验证结果。"


def test_transcript_endpoint_passes_material_terms_and_keeps_formal_transcript_read_only(training):
    h, headers, *_, speech = training
    row = wait(training, start(training).json()["training"]["id"], lambda r: r["phase"] == "answering")
    captured = []

    def transcribe(path, *, terms=None):
        captured.extend(terms or [])
        return {"text": "我使用Python与MySQL验证结果。", "seconds": 2, "provider": "isolated-asr"}

    speech.transcribe = transcribe
    qid = row["currentQuestion"]["id"]
    prefix = f"/api/v1/training/sessions/{row['id']}"
    response = h.client.post(prefix + "/transcripts", params={"question_id": qid}, content=b"synthetic-audio",
                             headers={**headers, "Idempotency-Key": str(uuid4())})
    assert response.status_code == 201
    assert {"Python", "MySQL"} <= set(captured)
    transcript = response.json()["transcript"]
    changed = h.client.post(prefix + "/answers", json={"question_id": qid, "method": "voice",
        "transcript_id": transcript["id"], "text": "修改原文"}, headers={**headers, "Idempotency-Key": str(uuid4())})
    assert changed.status_code == 422
    assert read(training, row["id"])["answers"] == []
    with h.app.state.session_factory() as db:
        asr = db.scalar(select(GenerationJob).where(GenerationJob.training_id == row["id"], GenerationJob.kind == "asr"))
        assert "terms" not in asr.input_snapshot and asr.state == "succeeded"
    assert not list(h.app.state.settings.speech_temporary_directory.glob("*.audio"))
