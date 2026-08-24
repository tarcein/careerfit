import os
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from models import (
    EssayDraftOutput,
    EvidenceItem,
    ExperienceData,
    ExperiencePreference,
    JDAnalysis,
    JDSkill,
    PersonalMaterial,
    ProfileData,
    QuestionAnalysis,
)
from services.document_parser import DocumentError, parse_document
from services.ai_service import (
    analyze_jd,
    analyze_question,
    extract_experiences,
    generate_essay_draft,
    generate_essay_outline,
    revise_essay_draft,
)
from services.application_review import evaluate_application, fact_check_draft
from services.matching import build_matching_report
from services.question_matching import (
    build_personal_material_report,
    build_question_matching_report,
    is_personal_question,
)
from services.recommendation_evaluation import calculate_ranking_metrics


class DocumentParserTests(unittest.TestCase):
    def test_txt_and_markdown(self):
        self.assertEqual(parse_document("work.txt", "프로젝트 결과".encode()), "프로젝트 결과")
        self.assertIn("제목", parse_document("work.md", "# 제목".encode()))

    def test_rejects_unsupported_and_empty(self):
        with self.assertRaises(DocumentError):
            parse_document("work.exe", b"data")
        with self.assertRaises(DocumentError):
            parse_document("work.txt", b"")

    def test_local_extraction_preserves_exact_evidence(self):
        files = [{"filename": "project.txt", "extracted_text": "고객 데이터를 분석했다.\n팀 성과는 전환율 10%다."}]
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            experiences, used_ai = extract_experiences(files, ProfileData())
        self.assertFalse(used_ai)
        self.assertEqual(experiences[0].evidence[0].quote, "고객 데이터를 분석했다.")
        self.assertEqual(experiences[0].ownership_notes.startswith("AI 미사용 초안"), True)

    def test_short_ai_draft_is_retried_to_reach_minimum_length(self):
        context = {
            "question": {"character_limit": 600},
            "jd": {"job_title": "개발자", "analysis": {}},
            "outline": {},
            "profile": {},
            "experiences": [{"profile": {}, "facts": [], "preferences": []}],
        }
        responses = [
            EssayDraftOutput(content="가" * 385),
            EssayDraftOutput(content="나" * 500 + "." + "다" * 199),
        ]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch(
            "services.ai_service.OPENAI_DRAFT_MODEL", "draft-model"
        ), patch("services.ai_service._parsed_response", side_effect=responses) as parsed:
            draft, used_ai = generate_essay_draft(context)
        self.assertTrue(used_ai)
        self.assertEqual(len(draft.content), 600)
        self.assertEqual(parsed.call_count, 2)
        self.assertTrue(all(call.args[5] == "draft-model" for call in parsed.call_args_list))

    def test_partial_draft_revision_preserves_other_paragraphs(self):
        context = {
            "question": {"character_limit": 600},
            "outline": {},
            "profile": {},
            "experiences": [],
            "materials": [],
        }
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch(
            "services.ai_service._parsed_response",
            return_value=EssayDraftOutput(content="수정된 첫 문단입니다."),
        ):
            revised = revise_essay_draft(
                context, "기존 첫 문단입니다.\n\n유지할 둘째 문단입니다.", "더 구체적으로", 0
            )
        self.assertEqual(revised.content, "수정된 첫 문단입니다.\n\n유지할 둘째 문단입니다.")


class RepositoryFlowTests(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(__file__).parent / ".careerfit-test.db"
        self.db_path.unlink(missing_ok=True)
        self.patch = patch.object(db, "DB_PATH", self.db_path)
        self.url_patch = patch.object(db, "DATABASE_URL", "")
        self.patch.start()
        self.url_patch.start()
        db.init_db()

    def tearDown(self):
        self.url_patch.stop()
        self.patch.stop()
        self.db_path.unlink(missing_ok=True)

    def test_account_login_and_profile_isolation(self):
        legacy_profile_id = db.create_user("기존 프로필")
        first_account_id = db.register_account("OWNER@Example.com", "password123", "기존 사용자")

        self.assertEqual(db.authenticate_account("owner@example.com", "password123")["id"], first_account_id)
        self.assertIsNone(db.authenticate_account("owner@example.com", "wrong-password"))
        self.assertIn(legacy_profile_id, [item["id"] for item in db.list_users(first_account_id)])

        second_account_id = db.register_account("second@example.com", "password456", "새 사용자")
        second_profiles = db.list_users(second_account_id)
        self.assertEqual(len(second_profiles), 1)
        self.assertNotIn(second_profiles[0]["id"], [item["id"] for item in db.list_users(first_account_id)])

    def test_profile_experience_version_and_approval(self):
        db.save_profile(ProfileData(nickname="테스터", target_role="Data Analyst"))
        self.assertEqual(db.get_profile().nickname, "테스터")

        file_id, created = db.add_uploaded_file("project.txt", ".txt", "hash", "stored", "근거 문장")
        self.assertTrue(created)
        file = db.get_uploaded_files([file_id])[0]
        experience = ExperienceData(
            experience_name="고객 분석",
            evidence=[EvidenceItem(source_file="project.txt", quote="근거 문장")],
            source_files=["project.txt"],
            confidence=0.7,
        )
        experience_id = db.create_experience(experience, [file])
        detail = db.get_experience(experience_id)
        self.assertEqual(detail["review_status"], "AI Extracted")
        self.assertEqual(detail["facts"][0]["evidence_text"], "근거 문장")

        preference = ExperiencePreference(target_role="Data Analyst", preferred_focus="전처리")
        db.save_preference(experience_id, preference)
        revised = experience.model_copy(update={"summary": "사용자 수정"})
        version_id = db.add_version(experience_id, revised, "요약 수정", "User", "사실 수정")
        db.approve_version(experience_id, version_id)
        verified = db.get_experience(experience_id)
        self.assertEqual(verified["review_status"], "Verified")
        self.assertEqual(verified["profile"]["summary"], "사용자 수정")
        self.assertEqual(len(verified["versions"]), 2)

    def test_personal_material_question_without_project(self):
        material_id = db.save_personal_material(
            PersonalMaterial(
                category="책",
                title="팩트풀니스",
                context="데이터 분석을 공부하며 읽은 책",
                memorable_point="직관보다 데이터를 확인해야 한다는 내용",
                insight="선입견을 수치로 검증하는 태도를 배움",
                changed_action="가설을 세우고 데이터로 먼저 확인함",
                keywords="데이터 검증 편견",
            )
        )
        material = db.get_personal_material(material_id)
        analysis = QuestionAnalysis(question_type="기타", important_points=["책", "영향", "행동 변화"])
        self.assertTrue(is_personal_question("감명 깊게 읽은 책을 소개해 주세요.", analysis))
        self.assertEqual(
            build_personal_material_report("감명 깊게 읽은 책", analysis, [material])[0]["id"],
            material_id,
        )

        jd_id = db.save_job_description(JDAnalysis(company="테스트", job_title="분석가"), "공고")
        question_id = db.save_essay_question(
            jd_id, "감명 깊게 읽은 책을 소개해 주세요.", None, "", analysis
        )
        question = db.get_essay_question(question_id)
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            outline, used_ai = generate_essay_outline(
                JDAnalysis(company="테스트", job_title="분석가"),
                question,
                [],
                personal_materials=[material],
            )
        self.assertFalse(used_ai)
        self.assertEqual(outline.experience_ids, [])
        self.assertEqual(outline.material_ids, [material_id])
        outline_id = db.save_essay_outline(question_id, None, outline)
        db.approve_essay_outline(outline_id)
        context = db.get_outline_context(outline_id)
        self.assertIsNone(context["experience"])
        self.assertEqual(context["materials"][0]["title"], "팩트풀니스")
        checks = fact_check_draft(
            "팩트풀니스를 읽고 선입견을 데이터로 검증하는 태도를 배웠습니다.",
            [],
            context["profile"],
            context["materials"],
        )
        self.assertEqual(checks[0].status, "Needs Review")
        db.delete_personal_material(material_id)
        self.assertEqual(db.list_essay_outlines(question_id), [])

    def test_application_folder_tracking(self):
        jd_id = db.save_job_description(JDAnalysis(company="회사", job_title="개발자"), "공고")
        db.update_application_tracking(jd_id, "작성 중", "2026-09-01", "1번 문항 보완")
        folder = db.list_application_folders()[0]
        self.assertEqual(folder["application_status"], "작성 중")
        self.assertEqual(folder["deadline"], "2026-09-01")
        self.assertEqual(folder["application_memo"], "1번 문항 보완")
        with self.assertRaises(ValueError):
            db.update_application_tracking(jd_id, "없는 상태")

    def test_source_facts_are_immutable(self):
        file_id, _ = db.add_uploaded_file("proof.txt", ".txt", "proof", "stored", "원본")
        file = db.get_uploaded_files([file_id])[0]
        experience_id = db.create_experience(
            ExperienceData(
                experience_name="근거 테스트",
                source_files=["proof.txt"],
                evidence=[EvidenceItem(source_file="proof.txt", quote="원본")],
            ),
            [file],
        )
        with self.assertRaises(sqlite3.IntegrityError), db.connect() as conn:
            conn.execute("UPDATE source_facts SET fact_text='변조' WHERE experience_id=?", (experience_id,))

        with self.assertRaises(sqlite3.IntegrityError), db.connect() as conn:
            conn.execute("DELETE FROM source_facts WHERE experience_id=?", (experience_id,))

        db.delete_experience(experience_id)
        self.assertIsNone(db.get_experience(experience_id))
        self.assertEqual(db.list_experiences(), [])
        self.assertEqual([item["id"] for item in db.list_uploaded_files()], [file_id])

    def test_jd_analysis_matching_and_gap_flow(self):
        raw_jd = "담당 업무: 고객 데이터 분석\n필수 자격: Python, SQL\n우대 사항: Tableau"
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            analysis, used_ai = analyze_jd("테스트컴퍼니", "Data Analyst", raw_jd)
        self.assertFalse(used_ai)
        self.assertEqual({skill.name for skill in analysis.required_skills}, {"Python", "SQL"})

        strong_file_id, _ = db.add_uploaded_file("strong.txt", ".txt", "strong", "stored", "Python SQL 분석 근거")
        weak_file_id, _ = db.add_uploaded_file("weak.txt", ".txt", "weak", "stored", "Excel 정리 근거")
        strong = ExperienceData(
            experience_name="고객 분석",
            summary="고객 데이터 분석",
            technical_skills=["Python", "SQL"],
            quantitative_results=["전환율 10%"],
            source_files=["strong.txt"],
            evidence=[EvidenceItem(source_file="strong.txt", quote="Python SQL 분석 근거")],
            confidence=0.9,
        )
        weak = ExperienceData(
            experience_name="문서 정리",
            summary="문서 정리",
            tools=["Excel"],
            source_files=["weak.txt"],
            evidence=[EvidenceItem(source_file="weak.txt", quote="Excel 정리 근거")],
            confidence=0.7,
        )
        strong_id = db.create_experience(strong, db.get_uploaded_files([strong_file_id]))
        weak_id = db.create_experience(weak, db.get_uploaded_files([weak_file_id]))
        db.approve_version(strong_id, db.get_experience(strong_id)["current_version_id"])
        db.approve_version(weak_id, db.get_experience(weak_id)["current_version_id"])

        jd_id = db.save_job_description(analysis, raw_jd)
        candidate_profile = ProfileData(
            major="Statistics",
            certifications="ADsP",
            languages="TOEIC 900",
            technical_skills="Tableau",
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            report = build_matching_report(
                jd_id, analysis, db.get_verified_experiences(), False, candidate_profile=candidate_profile
            )
        self.assertEqual(report["matches"][0]["experience_id"], strong_id)
        self.assertGreater(report["matches"][0]["score"], report["matches"][1]["score"])
        self.assertIn("SQL", report["matches"][0]["matching_skills"])
        self.assertEqual(next(item for item in report["gaps"] if item["skill"] == "SQL")["status"], "Strong")
        self.assertEqual(next(item for item in report["gaps"] if item["skill"] == "Tableau")["status"], "Strong")
        self.assertIn("자격증: ADsP", report["matches"][0]["explanation"]["profile_evidence"])

        db.save_match_results(jd_id, report["matches"])
        persisted = db.get_match_results(jd_id)
        self.assertEqual(persisted[0]["matching_skills"], report["matches"][0]["matching_skills"])
        db.save_recommendation_ground_truth(jd_id, [strong_id, weak_id])
        metrics = calculate_ranking_metrics(
            [{
                "predicted": [item["experience_id"] for item in persisted],
                "truth": [item["experience_id"] for item in db.get_recommendation_ground_truth(jd_id)],
            }]
        )
        self.assertEqual(metrics["top1_accuracy"], 100.0)
        self.assertEqual(metrics["recall_at_3"], 100.0)

    def test_profile_slots_isolate_data_and_mutations(self):
        second_user = db.create_user("프로필 2")
        db.save_profile(ProfileData(nickname="프로필 1", target_role="분석"), 1)
        db.save_profile(ProfileData(nickname="프로필 2", target_role="기획"), second_user)

        first_file, _ = db.add_uploaded_file("one.txt", ".txt", "same-hash", "one", "프로필 1 근거", 1)
        second_file, _ = db.add_uploaded_file(
            "two.txt", ".txt", "same-hash", "two", "프로필 2 근거", second_user
        )
        first_experience = db.create_experience(
            ExperienceData(
                experience_name="첫 번째 경험",
                source_files=["one.txt"],
                evidence=[EvidenceItem(source_file="one.txt", quote="프로필 1 근거")],
            ),
            db.get_uploaded_files([first_file], 1),
            1,
        )
        second_experience = db.create_experience(
            ExperienceData(
                experience_name="두 번째 경험",
                source_files=["two.txt"],
                evidence=[EvidenceItem(source_file="two.txt", quote="프로필 2 근거")],
            ),
            db.get_uploaded_files([second_file], second_user),
            second_user,
        )

        self.assertEqual([item["experience_name"] for item in db.list_experiences(1)], ["첫 번째 경험"])
        self.assertEqual(
            [item["experience_name"] for item in db.list_experiences(second_user)], ["두 번째 경험"]
        )
        self.assertIsNone(db.get_experience(first_experience, second_user))
        with self.assertRaises(ValueError):
            db.approve_version(first_experience, db.get_experience(first_experience, 1)["current_version_id"], second_user)

        self.assertEqual(db.approve_all_experiences(1), 1)
        self.assertEqual(db.get_experience(first_experience, 1)["review_status"], "Verified")
        self.assertEqual(db.get_experience(second_experience, second_user)["review_status"], "AI Extracted")
        self.assertEqual(db.approve_all_experiences(1), 0)

    def test_question_matching_outline_version_and_approval(self):
        db.save_profile(ProfileData(certifications="ADsP", languages="TOEIC 900"))
        jd = JDAnalysis(
            company="Test Co",
            job_title="Data Analyst",
            main_tasks=["Analyze customer data"],
            required_skills=[JDSkill(name="Python", importance=1.0)],
            technical_skills=[JDSkill(name="SQL", importance=0.8)],
        )
        jd_id = db.save_job_description(jd, "Python and SQL customer analysis")
        file_id, _ = db.add_uploaded_file(
            "problem.txt", ".txt", "problem-hash", "stored", "Used Python to find the cause and improved conversion by 10%."
        )
        experience = ExperienceData(
            experience_name="Conversion diagnosis",
            summary="Diagnosed a conversion problem with data",
            problem="Conversion was falling",
            decision="Analyze funnel data",
            actions=["Used Python and SQL to isolate the cause"],
            result="Conversion improved",
            quantitative_results=["10% improvement"],
            technical_skills=["Python", "SQL"],
            lessons=["Validate assumptions with data"],
            source_files=["problem.txt"],
            evidence=[
                EvidenceItem(
                    source_file="problem.txt",
                    quote="Used Python to find the cause and improved conversion by 10%.",
                )
            ],
            confidence=0.9,
        )
        experience_id = db.create_experience(experience, db.get_uploaded_files([file_id]))
        db.approve_version(experience_id, db.get_experience(experience_id)["current_version_id"])
        support_file_id, _ = db.add_uploaded_file(
            "dashboard.txt", ".txt", "dashboard-hash", "stored", "Built a Tableau dashboard for stakeholders."
        )
        support_id = db.create_experience(
            ExperienceData(
                experience_name="Stakeholder dashboard",
                summary="Shared analysis through a dashboard",
                result="Stakeholders reviewed the findings",
                tools=["Tableau"],
                source_files=["dashboard.txt"],
                evidence=[EvidenceItem(source_file="dashboard.txt", quote="Built a Tableau dashboard for stakeholders.")],
                confidence=0.9,
            ),
            db.get_uploaded_files([support_file_id]),
        )
        db.approve_version(support_id, db.get_experience(support_id)["current_version_id"])

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            analysis, used_ai = analyze_question("문제를 해결한 경험을 설명해 주세요.", "", jd)
        self.assertFalse(used_ai)
        self.assertEqual(analysis.question_type, "문제해결")
        question_id = db.save_essay_question(jd_id, "문제를 해결한 경험", 700, "", analysis)
        matches = build_question_matching_report(jd_id, jd, analysis, db.get_verified_experiences())
        self.assertEqual(matches[0]["experience_id"], experience_id)
        db.save_question_match_results(jd_id, question_id, matches)
        self.assertEqual(db.get_question_match_results(question_id)[0]["rank"], 1)

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            outline, outline_used_ai = generate_essay_outline(
                jd,
                db.get_essay_question(question_id),
                [db.get_experience(experience_id), db.get_experience(support_id)],
                candidate_profile=db.get_profile(),
            )
        self.assertFalse(outline_used_ai)
        self.assertEqual(outline.experience_ids, [experience_id, support_id])
        self.assertIn("Built a Tableau dashboard for stakeholders.", outline.evidence_used)
        self.assertIn("지원자 프로필 근거", [section.title for section in outline.sections])
        first_outline_id = db.save_essay_outline(question_id, experience_id, outline)
        second_outline_id = db.save_essay_outline(
            question_id, experience_id, outline.model_copy(update={"key_message": "Revised message"})
        )
        db.approve_essay_outline(second_outline_id)
        saved = db.list_essay_outlines(question_id)
        self.assertEqual([item["version_number"] for item in saved], [2, 1])
        self.assertEqual(next(item for item in saved if item["id"] == second_outline_id)["is_approved"], 1)
        self.assertEqual(next(item for item in saved if item["id"] == first_outline_id)["is_approved"], 0)

        context = db.get_outline_context(second_outline_id)
        self.assertEqual([item["id"] for item in context["experiences"]], [experience_id, support_id])
        limited_context = context | {"question": context["question"] | {"character_limit": 80}}
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            limited_draft, _ = generate_essay_draft(limited_context)
        self.assertLessEqual(len(limited_draft.content), 80)
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            draft, draft_used_ai = generate_essay_draft(context)
        self.assertFalse(draft_used_ai)
        self.assertIn("10% improvement", draft.content)
        with self.assertRaises(ValueError):
            db.save_essay_draft(first_outline_id, draft.content)
        draft_id = db.save_essay_draft(second_outline_id, draft.content)
        with self.assertRaises(ValueError):
            db.save_essay_draft(second_outline_id, "x" * 701)
        checks = fact_check_draft(draft.content, context["experiences"], context["profile"])
        self.assertTrue(checks)
        self.assertFalse(any(item.status == "Unsupported" for item in checks))
        support_check = fact_check_draft("Built a Tableau dashboard for stakeholders.", context["experiences"])
        self.assertEqual(support_check[0].status, "Verified")
        profile_check = fact_check_draft("자격증 ADsP", context["experiences"], context["profile"])
        self.assertEqual(profile_check[0].status, "Needs Review")
        self.assertIn("My Profile 자격증: ADsP", profile_check[0].evidence)
        unsupported = fact_check_draft("I improved conversion by 99%.", context["experiences"])
        self.assertEqual(unsupported[0].status, "Unsupported")
        db.save_fact_check_results(second_outline_id, draft_id, checks)
        self.assertEqual(len(db.get_fact_check_results(draft_id)), len(checks))
        quality = evaluate_application(draft.content, context, checks, db.count_experience_uses(jd_id, experience_id))
        self.assertTrue(quality["character_limit_ok"])
        self.assertEqual(quality["experience_use_count"], 1)
        self.assertEqual(db.get_dashboard_metrics()["drafts"], 1)
        self.assertIn("Python", {item["skill_name"] for item in db.list_jd_skill_frequencies()})

        db.delete_essay_draft(draft_id)
        self.assertEqual(db.list_essay_drafts(second_outline_id), [])
        db.delete_essay_outline(second_outline_id)
        self.assertIsNone(db.get_outline_context(second_outline_id))
        db.delete_essay_question(question_id)
        self.assertEqual(db.list_essay_questions(jd_id), [])
        cascade_question_id = db.save_essay_question(jd_id, "삭제 확인 문항", 300, "", analysis)
        db.delete_job_description(jd_id)
        self.assertIsNone(db.get_job_description(jd_id))
        self.assertIsNone(db.get_essay_question(cascade_question_id))


if __name__ == "__main__":
    unittest.main()
