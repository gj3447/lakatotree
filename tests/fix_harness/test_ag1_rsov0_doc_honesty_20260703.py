"""AG1/R-SOV-0 doc-honesty 가드 — 재현확인(reproduction-confirmation) ≠ 값소유(value-ownership) 어휘 한계선.

측정주권 PROM(2026-07-03) first_move. 코드 실측(정찰 wf_48a54c6b): replay 는 '스크립트가 기록값을
재현하나' bool 확인(server/app.py `return v.verified`, 재유도값 폐기, LAKATOS_REPLAY_EXEC 기본
OFF=dead path)이고, :VerdictReceipt(RECEIPT_FIELDS 12필드)는 client float 를 봉인·운반할 뿐
measurement_grade 가 없다. 그러므로 정본 문서 표면의 무단서 현재시제 '외부 측정/위조 닫힘/거짓말
불가'는 과대표현이다 — 이 가드가 그 어휘를 기계적으로 잠근다(docs/ADR-measurement-sovereignty-20260703.md).

  guard_defect    = test_confirmed_overclaims_are_dead   (음성: 확정 과대표현 3건 부활 시 RED)
  guard_mechanism = test_adr_exists_and_pins_code        (양성: ADR 실재 + 필수 어휘 + 가드 포인터)
                    test_adr_code_anchors_hold           (양성: claim↔code 1:1 — AG3/AG6 착륙 시 RED 로 ADR 개정 강제)

노드의 novel_script = 이 파일 — mechanism 실재해야 progressive, revert-민감.
# KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag1_rsov0_doc_honesty
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR = ROOT / "docs" / "ADR-measurement-sovereignty-20260703.md"


def test_confirmed_overclaims_are_dead():
    tts = (ROOT / "TOUCH_THE_SKY.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    # ① TTS — 미구현 G-Web 재fetch 를 현재시제 '닫는다'로 서술하던 문장은 죽었고, 교정문은 미구현을 명시
    assert "잔여 위조(특정 출판사 URL 을 사칭)는 재fetch 가 닫는다" not in tts
    tail = tts.split("잔여 위조(특정 출판사 URL 을 사칭)")[1][:160]
    assert "미구현" in tail, f"교정문이 미구현 단서를 잃음: {tail!r}"
    # ② TTS — '거짓말할 수 없는'은 각주(측정층 한계 공개) 직결 없이는 무단서 현재시제
    sent = "이 DNA는 거짓말할 수 없는 채로 오른다."
    hits = [m.end() for m in re.finditer(re.escape(sent), tts)]
    assert hits, "문장 자체가 사라짐 — 가드 재조준 필요(문서 리라이트?)"
    for end in hits:
        assert tts[end:end + 2] == "[^", "TTS '거짓말할 수 없는' 각주 없는 재발"
    # ③ README 헤드라인 — 외부성 무단서 현재시제는 죽었고, 한계선 어휘가 들어옴
    assert "and an external measurement" not in readme
    assert "reproduction-confirmation, not value-ownership" in readme


def test_adr_exists_and_pins_code():
    adr = ADR.read_text(encoding="utf-8")
    for needle in ("재현확인", "값소유", "reproduction-confirmation", "value-ownership",
                   "RECEIPT_FIELDS", "measurement_grade", "LAKATOS_REPLAY_EXEC",
                   "return v.verified", "client float"):
        assert needle in adr, f"ADR 필수 어휘 누락: {needle}"
    # 상태절이 이 가드 파일을 가리킨다(ADR 관례)
    assert "test_ag1_rsov0_doc_honesty_20260703.py" in adr


def test_adr_code_anchors_hold():
    """claim↔code 1:1 — ADR 이 서술한 '현 한계선'이 코드에 실재함을 실행으로 검증.

    의도된 tripwire: AG3(measurement_grade 봉인)·AG6(값무결 fsck)가 착륙해 코드가 바뀌면
    이 테스트가 RED 가 되어 ADR 개정을 기계적으로 강제한다(문서-코드 드리프트 봉쇄)."""
    from lakatos.verdicts import RECEIPT_FIELDS, fold_receipt_chain
    assert "measurement_grade" not in RECEIPT_FIELDS
    assert set(RECEIPT_FIELDS) == {
        "tree", "tag", "target_id", "verdict", "verdict_source", "metric_name", "metric_value",
        "novel_confirmed", "lakatos_status", "judged_at", "judge_script_sha", "prev_receipt_sha"}
    app = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
    assert "return v.verified" in app            # replay = verified bool 반환(재유도값 서버경계 폐기)
    assert "LAKATOS_REPLAY_EXEC" in app          # exec 게이트 실재(기본 OFF)
    fold_src = inspect.getsource(fold_receipt_chain)
    assert "receipt_content_sha" not in fold_src and "canonical_receipt_blob" not in fold_src, \
        "fold 가 내용해시 재대조를 시작함 — ADR '포인터 워크' 서술 개정 필요"
