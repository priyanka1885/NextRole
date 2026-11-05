"""
06_review_needs_review.py — DEPRECATED for the current golden_eval_dataset.csv.

As of the 2024 pipeline revision, 04_build_golden.py samples ONLY the two
confident/machine_annotated buckets (good_fit_confident + no_fit_confident =
70 records). It never produces any "needs_review" rows in the golden set,
so there is nothing for this script to review: running it against the
current golden_eval_dataset.csv will safely no-op/error out (it checks for
both a "needs_review" row count of 0 AND a "review_decision" column that
no longer exists in the golden schema, and reports that clearly instead of
silently doing nothing or corrupting the file).

This file, and the DECISIONS dict below, are KEPT (not deleted) purely as a
historical record of the independent LLM review that was previously
integrated into an earlier 100-record version of the golden set (30
llm_reviewed + 70 machine_annotated). That edge-case/LLM-review layer was
intentionally removed from the golden-set build per explicit instruction;
the Potential Fit / label-conflict / insufficient-signal records it used to
cover still exist in the full annotated_dataset.csv backlog for future
human review (see human_review_checklist.md), just no longer in the
sampled golden set.

--- Original module docstring follows, describing what this script did when
it was part of the active pipeline ---

06_review_needs_review.py — Integrates the independent LLM review of the
`needs_review` golden-set records DIRECTLY into golden_eval_dataset.csv
and .jsonl — ONE dataset, no separate file.

IMPORTANT PROVENANCE NOTE:
This review was performed by an AI assistant (LLM) reading each full
resume + job description and comparing skills/experience/qualifications
against the JD's stated (and implied mandatory) requirements. It is
NOT a human review. It is recorded via `annotation_status = "llm_reviewed"`
— never `human_verified` — so provenance stays honest.

STRUCTURED VERDICT FIELD:
The LLM's verdict is written to a dedicated `review_decision` column
(values: "Fit", "No Fit", "Exclude" — blank for every record this stage
doesn't touch). `expected_decision` — the strict 3-class source-of-truth
label used for exact-match evaluation metrics (per requirements.md §21) —
is never overwritten by this stage, including for the "Exclude" verdict,
which deliberately isn't a valid value in that enum (overwriting it there
would corrupt it for scoring purposes). For narrative/human-readable
traceability, the same decision + reasoning is ALSO appended (not
substituted) into the existing free-text fields:
  - decision_reason: original text kept intact as a prefix, followed by
    " | LLM independent review: <decision> — <reasoning>"
  - annotation_source: original value kept intact as a prefix, followed by
    "+llm_reviewed"
  - annotation_status: "needs_review" -> "llm_reviewed" (a status flag,
    not a protected field)
  - expected_decision: left COMPLETELY UNCHANGED for every row, per
    explicit instruction not to overwrite it with an LLM judgment.

The already-`machine_annotated` rows, and every other column for every
row, are untouched.

MATCHING THE CURATED DECISIONS TO THE ACTUAL SELECTED RECORDS:
The DECISIONS dict below was curated against a specific run of
04_build_golden.py (fixed SEED=42 against a specific train.csv /
annotated_dataset.csv). Before applying anything, this script verifies
that the set of (resume_id, job_id, expected_decision) keys currently
marked `needs_review` in the golden set is EXACTLY the set of keys
present in DECISIONS — no more, no fewer. Any mismatch (a currently
needs_review row with no curated decision, or a curated decision that no
longer corresponds to any needs_review row — e.g. because the golden set
was resampled) is reported explicitly and the script exits non-zero
instead of silently applying a partial or stale review.

Run:
    python dataset/scripts/06_review_needs_review.py
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "dataset" / "output"
REVIEWED_BY = "Kiro AI assistant (LLM-based independent review, NOT a human reviewer)"
REVIEWED_AT = "2026-11-05"

# Key = (resume_id, job_id, expected_decision) — matches the same key used
# elsewhere in the pipeline to disambiguate label_conflict_edge duplicate pairs.
# Decision in {"Fit", "No Fit", "Exclude"}.
DECISIONS = {
    ("RES_49c50302dc", "JOB_5223e70ea2", "Potential Fit"): ("No Fit",
        "JD requires 10+ years SFDC/Salesforce Industries Communications Cloud experience plus 5+ years "
        "Telecom Quote-to-Cash domain (Vlocity/Omnistudio). Resume shows a 4-year-career IoT embedded "
        "software engineer (C, AWS IoT Core, Perforce) with zero Salesforce, Vlocity, or telecom-domain "
        "experience. Mandatory core platform and years-of-experience requirements are both unmet."),
    ("RES_0f76bb1639", "JOB_e839f2a261", "Potential Fit"): ("No Fit",
        "JD requires a software/cloud Data Engineer: 6+ years building data pipelines on AWS/Azure/GCP, "
        "Python, SQL Server, SSIS, Bachelor's in CS/Engineering. Resume's 'Data Engineer' title is from "
        "oil-field mud logging/drilling operations (Baker Hughes) with a Geology degree; no cloud, ETL, "
        "SQL, or programming skills are listed. Shared job-title wording masks an unrelated domain."),
    ("RES_b9ee180c5b", "JOB_f5ff712a96", "Potential Fit"): ("No Fit",
        "JD requires 8+ years Fullstack Java Engineer: Spring, Hibernate, J2EE, JSF, Oracle, JUnit. Resume "
        "is a Microsoft-stack engineer (MSSQL, C#, ASP.NET MVC, Entity Framework) with no Java, Spring, or "
        "Hibernate anywhere. Sufficient years of general experience, but the entire required tech ecosystem "
        "is absent — a different platform, not a transferable skill gap."),
    ("RES_e5c91b3c93", "JOB_5d6cde0fe1", "Potential Fit"): ("No Fit",
        "JD's essential skill is Java Spring Boot (C#/.NET considered), plus React/AWS/Kubernetes/Docker, "
        "5+ years full-stack. Resume is a Pega PRPC (BPM/low-code) specialist with ~3 years directly "
        "relevant dev experience; no Spring Boot, React, AWS, Docker, or Kubernetes appear anywhere. "
        "Core essential skill and minimum relevant years are both unmet."),
    ("RES_1264486ede", "JOB_b22d1c5ce0", "Potential Fit"): ("Fit",
        "JD requires 5+ years Java, AWS, data modeling/NoSQL, Microservices/Docker/Kubernetes, Python, "
        "BS/MS in a related field. Resume shows ~10 years as a Software Engineer on an IoT cloud platform "
        "using AWS, Kubernetes, Docker, Kafka, Cassandra (NoSQL), Python, and Java, plus an MS in "
        "Computational Statistics & Machine Learning. All core requirements are substantively met; the "
        "resume's leading 'Sales Associate' summary line is an unrelated boilerplate artifact, not a "
        "reflection of the candidate's actual (software engineering) background shown in the rest of the resume."),
    ("RES_49c50302dc", "JOB_31dcdd3280", "Potential Fit"): ("No Fit",
        "JD requires an 8+ years' (or Master's + 6+ years) Software Development MANAGER supervising "
        "15-20 staff, with ITS/V2X/connected-vehicle domain knowledge. Resume shows a Bachelor's-level "
        "candidate with only 4 years total experience and zero people-management experience (same "
        "candidate as the Salesforce-BA mismatch above). Both the seniority/management scope and years "
        "requirement are unmet by a wide margin."),
    ("RES_ccc3f906c4", "JOB_35f1df5147", "Potential Fit"): ("No Fit",
        "JD requires 5+ years specifically in revenue recognition/billing (ASC 606), Bachelor's in "
        "Finance/Accounting. Resume shows a Master's in Accounting (exceeds degree requirement) but only "
        "a brief ~9-month 'Revenue Accountant' stint; most other roles are general accounting/financial-aid, "
        "not revenue-specific. The 5+ year revenue/billing experience requirement is not demonstrated."),
    ("RES_3a2c089ff4", "JOB_fb8fdce93b", "Potential Fit"): ("Fit",
        "JD requires BS Accounting/Finance + 5+ years relevant experience, financial statements, journal "
        "entries, audits, budgets. Resume shows ~6 years of accounting roles including a current 'Senior "
        "Accountant' title (Expedia), with direct experience in reconciliations, journal entries, fixed "
        "assets, and audit support, plus a Master's in Business Administration/Accounting. Core duties and "
        "experience level match well; an unrelated 'Guest services/Merchandising' Skills-section artifact "
        "does not reflect the substantive Experience section."),
    ("RES_5deefc9ce9", "JOB_0533b89e73", "Potential Fit"): ("No Fit",
        "JD requires 5-10 years of public accounting experience, tax return preparation (1040/1065/1120S), "
        "CPA preferred. Resume's background is predominantly sales/marketing account management (Account "
        "Manager roles driving ad revenue and sales growth); the one 'Interim Accountant' entry has "
        "corrupted/placeholder dates and describes only basic bookkeeping. No tax prep, no CPA, no public "
        "accounting tenure approaching 5-10 years."),
    ("RES_927b0eadfb", "JOB_35d5a080de", "Potential Fit"): ("Exclude",
        "The job_description_text is a single 72-character sentence ('I own a small landscaping business "
        "that needs help with accounting/taxes') with no stated qualifications, scope, or requirements. "
        "There is not enough substantive JD content to perform a genuine mandatory-requirements comparison "
        "(the resume itself — Staff Accountant/Seasonal Tax Preparer, Master of Accountancy, CPA exam "
        "completed — looks plausibly relevant, but the posting is not a usable evaluation example). "
        "Recommend excluding this record from the matching-agent evaluation set rather than forcing a "
        "Fit/No Fit call on an inadequate JD."),
    ("RES_264f98bda7", "JOB_6370a8a880", "Potential Fit"): ("No Fit",
        "JD requires 8+ years Java/J2EE with Spring (Core/MVC/Boot/Batch/Microservices), Hibernate, MongoDB. "
        "Resume shows 17 years IT experience (exceeds years requirement) but entirely in the .NET/C# stack "
        "(ASP.NET, MVC 4, SQL Server, Crystal Reports); no Java, Spring, or Hibernate anywhere. Sufficient "
        "seniority, wrong technology ecosystem entirely."),
    ("RES_744b9b6372", "JOB_f5ff712a96", "Potential Fit"): ("No Fit",
        "Same 'Fullstack Java Engineer' JD as above (8+ years Java/Spring/Hibernate/J2EE, BS CS). Resume is "
        "a Senior Software QA/Test Engineer (functional/UAT/regression testing, QTP, HP Quality Center) with "
        "a Business Administration/Commerce education — a QA/testing discipline, not software development, "
        "and no CS degree. Fundamental role-type mismatch, not a skills gap within the same role."),
    ("RES_e5a9b688d9", "JOB_36a5aa1a4b", "Potential Fit"): ("No Fit",
        "JD's named 'chosen instruments' are Node.js (backend) and AWS (cloud), plus React frontend. Resume "
        "shows strong full-stack experience but on Ruby on Rails (not Node.js) and Azure DevOps (not AWS); "
        "React/REST/CI-CD/Git skills do match. The two explicitly central technologies for this specific "
        "role (Node.js, AWS) are both absent, despite solid adjacent full-stack competence."),
    ("RES_919ead406b", "JOB_34a0152e0c", "Potential Fit"): ("Fit",
        "JD requires 3-5 years as a Data Analyst, Bachelor's degree, Excel/pivot tables, Power BI, Python/R, "
        "SQL/Oracle. Resume shows a 10-year Business Intelligence Consultant/Senior Data Engineer with "
        "direct experience in Power BI, Python, SQL/Oracle/Teradata, and an IT Bachelor's degree — exceeding "
        "the experience minimum and matching the core named tools, despite being more senior/ETL-focused "
        "than a typical 'Data Analyst' title and lacking the Power Apps/Google Analytics nice-to-haves."),
    ("RES_aaf39bf3b2", "JOB_25d11f4f8e", "Potential Fit"): ("No Fit",
        "JD requires a minimum 7 years specifically as an Agile Business Analyst on a technical development "
        "team (user stories, acceptance criteria, backlog refinement). Resume shows only ~2 years in a "
        "'Business System Analyst' title (2009-2011); the bulk of the 7+ year career (2011-2016+) was spent "
        "as a Data Scientist, a different discipline. The mandatory 7-year BA-specific tenure is not met."),
    ("RES_e0dfc10511", "JOB_7235b3d3b3", "Potential Fit"): ("Fit",
        "JD requires 15+ years software engineering in C/Java, 10+ years leading engineering teams, 5+ "
        "years financial services/payments. Resume shows 19 years of Java-centric engineering, multiple "
        "'Lead Software Engineer' titles with direct reports managed over ~6.5 years, and ~6.5 years on "
        "financial-services (asset management/iShares) platforms. Core experience and leadership thresholds "
        "are substantively met even though payments-processing specifically isn't named (asset management "
        "counts as financial services)."),
    ("RES_85d06aafe8", "JOB_e7ef7ef1d1", "Potential Fit"): ("Fit",
        "JD requires a BS in CS/STEM plus (desired) Python, SQL (multiple RDBMS), ETL exposure, Power "
        "BI/Tableau. Resume shows a BS in Electronics & Communication Engineering (STEM) and direct, strong "
        "experience in Python, SQL across platforms, Talend/Informatica ETL, AWS, and Power BI/Tableau "
        "listed tools. Only the niche aviation-specific 'aircraft data frames' nice-to-have is unmet, which "
        "the JD itself treats as non-mandatory."),
    ("RES_75918afbf5", "JOB_f5ac323b1e", "Potential Fit"): ("Fit",
        "JD requires 8-12 years in the Data Quality field with SQL skills (named tools Collibra/Jira/"
        "Confluence are client-specific preferences). Resume shows 10+ years as a Data Analyst with 'Data "
        "Quality', 'Data Validation', 'Data Integrity Validation', and 'Data Mapping' explicitly listed as "
        "core skills, matching the stated functional domain and years even though the specific named tools "
        "aren't confirmed."),
    ("RES_e5a9b688d9", "JOB_47d47d7ed7", "Potential Fit"): ("No Fit",
        "JD requires a Software Engineer IN TEST: Core Java, Selenium, TestNG, BDD test automation. Resume "
        "is a Ruby on Rails full-stack developer with no Java, no Selenium/TestNG/BDD, and no test-automation "
        "framework experience anywhere — a backend development profile, not a test-engineering one."),
    ("RES_770364f2de", "JOB_ded37a863e", "Potential Fit"): ("Fit",
        "JD requires a Bachelor's + 2-3 years in ETL/data pipelines/SQL/big-data concepts, with banking/"
        "financial-services experience preferred. Resume shows 9 years of ETL/Data Engineering (DataStage, "
        "Informatica, Spark, Azure) — well exceeding the requirement — plus financial-services-adjacent "
        "employers (Factset Research Systems, an insurance/annuity MDM project). Both required and "
        "preferred criteria are comfortably exceeded."),
    ("RES_1264486ede", "JOB_627f2909c3", "No Fit"): ("No Fit",
        "CONFLICT PAIR (this resume+JD combo carries two contradictory original labels: 'No Fit' and "
        "'Potential Fit'). JD requires 5-9 years as an ERP Business Analyst with Dynamics 365/SAP/NetSuite "
        "functional and financial-module experience, full ERP implementation lifecycle, manufacturing/CPG "
        "a plus. Resume is a cloud/backend Software Engineer (AWS, Kubernetes, microservices) with zero ERP, "
        "Business Analyst, or manufacturing/CPG experience. Independent review sides with the 'No Fit' "
        "label; 'Potential Fit' appears to be the erroneous occurrence."),
    ("RES_80dfe41bd0", "JOB_ab8529aa02", "No Fit"): ("No Fit",
        "CONFLICT PAIR (this resume+JD combo carries two contradictory original labels: 'No Fit' and "
        "'Good Fit'). JD requires 10+ years specifically as a Business Analyst with team-leadership "
        "experience. Resume's career is Network Administrator -> SQL/BI Developer (Power BI, Tableau, "
        "SSIS/SSRS); the resume itself states 'Worked WITH Business Analysts to understand requirements', "
        "i.e. the candidate supports BAs rather than performing the BA role, and no team-leadership "
        "experience is shown. Independent review sides with the 'No Fit' label; 'Good Fit' appears to be "
        "the erroneous occurrence."),
    ("RES_1264486ede", "JOB_627f2909c3", "Potential Fit"): ("No Fit",
        "Second row of the same conflicting pair above (resume_id=RES_1264486ede, job_id=JOB_627f2909c3). "
        "Same resume and JD text; same evidence applies: a cloud/backend Software Engineer has no ERP, "
        "Business Analyst, or manufacturing/CPG experience against an ERP Business Analyst JD. 'No Fit' is "
        "the correct decision for both occurrences of this pair."),
    ("RES_80dfe41bd0", "JOB_ab8529aa02", "Good Fit"): ("No Fit",
        "Second row of the same conflicting pair above (resume_id=RES_80dfe41bd0, job_id=JOB_ab8529aa02). "
        "Same resume and JD text; same evidence applies: a SQL/BI developer who explicitly supports Business "
        "Analysts (rather than acting as one) does not meet a 10+ year senior Business Analyst requirement "
        "with team leadership. 'No Fit' is the correct decision for both occurrences of this pair."),
    ("RES_de775ddf14", "JOB_ea6dc9293d", "Good Fit"): ("No Fit",
        "JD requires 4-6 years hands-on Microsoft Dynamics 365 (X++, ADO), with experience LEADING a team "
        "of developers and Supply Chain domain knowledge. Resume is a Java/Spring/Hibernate/Oracle enterprise "
        "developer with an ML/academic background; it contains zero mentions of Dynamics 365, X++, ADO, or "
        "Supply Chain, and no team-leadership role (individual-contributor 'Software Developer' plus a "
        "teaching-assistant stint). This overturns the original 'Good Fit' label — the core platform and "
        "leadership requirements are both unmet."),
    ("RES_d9d1f667fc", "JOB_39d5e426a0", "Good Fit"): ("Fit",
        "JD requires 7+ years accounting experience (4+ as a senior accountant), Bachelor's in Accounting/"
        "Finance, public accounting a plus. Resume shows 7+ combined years across India audit work (public "
        "accounting — a stated plus), Nepal Chartered Accountant practice, and a current US 'Staff "
        "Accountant' role whose actual duties (multi-entity consolidation, intercompany reconciliation, "
        "10-K/10-Q disclosure prep) are senior-level in substance despite the 'Staff' job title. Education "
        "(MS Accounting) exceeds the requirement. Core experience and duties substantively match."),
    ("RES_b31ae43162", "JOB_c5ff4d6a4d", "Good Fit"): ("No Fit",
        "JD requires a Principal Cloud Software Engineer: 10+ years, extensive AWS (Lambda/RDS/DynamoDB/"
        "CloudFormation/EC2), Java, SQL, JavaScript, fintech domain knowledge, team leadership. Resume is a "
        "Senior QA/Validation & Verification Engineer in medical-device/pharma diagnostics (immunoassay "
        "analyzers) with a Biology/Pharmaceutical Systems Management background — zero software engineering, "
        "zero AWS/cloud, zero Java/SQL/JavaScript, zero fintech. This overturns the original 'Good Fit' "
        "label — there is no overlap on any required technical skill or domain."),
    ("RES_ad78bf273d", "JOB_c5ff4d6a4d", "No Fit"): ("No Fit",
        "Same Principal Cloud Software Engineer JD as above. Resume is an experienced .NET/C# developer "
        "(16 years, ASP.NET MVC, Angular, Entity Framework, SQL Server) with a relevant CS degree and "
        "sufficient years, but zero AWS/cloud services (JD requires 'extensive knowledge' of several named "
        "AWS services), no Java, and no fintech-domain employers. The core required cloud platform and "
        "language are both absent, confirming the original 'No Fit' label."),
    ("RES_647dd5b777", "JOB_59dcf38a19", "No Fit"): ("No Fit",
        "JD requires 7+ years of client-focused business/requirements analysis with at least 2 years in a "
        "BA leadership role. Resume shows roughly 1 year as a 'Data Analyst' (Humana) with the remainder of "
        "the career in childcare teaching, administrative assistant, and front-desk reception roles. The "
        "7-year experience minimum is unmet by a wide margin, confirming the original 'No Fit' label."),
    ("RES_3113cc92f2", "JOB_577c3011c2", "No Fit"): ("No Fit",
        "JD requires 3+ years preparing complex tax returns (1040/1065/1120S) in a CPA firm, pursuing/"
        "holding EA or CPA, QuickBooks Online familiarity. Resume's entire career (Principal Technical "
        "Consultant, Instrument Reliability Group Leader, Process Control Engineer) is industrial "
        "instrumentation/process-safety engineering in oil & gas/chemical plants, with a Chemical "
        "Engineering degree and a Functional Safety Engineer certification — zero accounting, tax, or "
        "CPA/EA background. Confirms the original 'No Fit' label; an unrelated 'Sales Associate' summary "
        "line is a boilerplate artifact, not evidence of relevant experience."),
}


MARKER = "LLM independent review:"
VALID_REVIEW_DECISIONS = {"Fit", "No Fit", "Exclude"}


def main():
    csv_path = OUT_DIR / "golden_eval_dataset.csv"
    jsonl_path = OUT_DIR / "golden_eval_dataset.jsonl"

    if not csv_path.exists():
        raise FileNotFoundError(f"{csv_path} not found — run 04_build_golden.py first.")

    # Sanity-check the curated DECISIONS dict itself before touching any data.
    bad_decisions = {k: v[0] for k, v in DECISIONS.items() if v[0] not in VALID_REVIEW_DECISIONS}
    if bad_decisions:
        raise SystemExit(f"ERROR: DECISIONS contains invalid verdict value(s): {bad_decisions}")

    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    if "review_decision" not in df.columns:
        raise SystemExit(
            "This script is deprecated for the current golden_eval_dataset.csv: it has no "
            "'review_decision' column because 04_build_golden.py now builds a 70-record, "
            "machine_annotated-only golden set with no needs_review rows to review. See the "
            "module docstring at the top of this file for details. Nothing to do here."
        )

    # Text fields store embedded newlines escaped as literal "\n" (see
    # 04_build_golden.py). Unescape to real newlines in memory so JSONL
    # round-trips correctly; re-escape only at CSV write time below.
    for col in ["resume_text", "job_description_text"]:
        df[col] = df[col].str.replace("\\n", "\n", regex=False)

    needs_review_mask = df["annotation_status"] == "needs_review"
    already_reviewed_mask = df["annotation_status"] == "llm_reviewed"
    n_needs_review = int(needs_review_mask.sum())
    n_already_reviewed = int(already_reviewed_mask.sum())

    if n_needs_review == 0 and n_already_reviewed == 0:
        raise SystemExit(
            "ERROR: found 0 'needs_review' and 0 'llm_reviewed' rows in golden_eval_dataset.csv — "
            "has 04_build_golden.py actually been run, and does the file have any rows?"
        )

    if n_needs_review == 0:
        # Fully idempotent no-op: every row that was ever needs_review has
        # already been reviewed in a prior run. Report clearly instead of
        # crashing on a stale hardcoded count.
        print(f"Nothing to do: 0 'needs_review' rows remain ({n_already_reviewed} already 'llm_reviewed'). "
              f"06_review_needs_review.py has already been fully integrated for this golden set.")
        return

    # Verify the curated DECISIONS keys match the CURRENT needs_review rows
    # exactly — report any shortage (needs_review rows with no decision) and
    # any surplus (stale decisions that no longer match a real row), rather
    # than assuming a fixed count and silently applying a partial review.
    current_keys = {
        (row["resume_id"], row["job_id"], row["expected_decision"])
        for _, row in df[needs_review_mask].iterrows()
    }
    decision_keys = set(DECISIONS.keys())
    missing_keys = sorted(current_keys - decision_keys)   # needs_review rows with no curated decision
    unused_keys = sorted(decision_keys - current_keys)    # curated decisions matching no current row

    if missing_keys or unused_keys:
        lines = [f"ERROR: curated DECISIONS do not match the {n_needs_review} current needs_review rows."]
        if missing_keys:
            lines.append(f"  {len(missing_keys)} needs_review row(s) have NO curated decision: {missing_keys}")
        if unused_keys:
            lines.append(f"  {len(unused_keys)} curated decision(s) match NO current needs_review row "
                          f"(stale — likely the golden set was resampled): {unused_keys}")
        raise SystemExit("\n".join(lines))

    updated = 0
    for idx, row in df[needs_review_mask].iterrows():
        key = (row["resume_id"], row["job_id"], row["expected_decision"])
        decision, reasoning = DECISIONS[key]
        if MARKER in row["decision_reason"]:
            continue  # already integrated; idempotent re-run
        df.at[idx, "decision_reason"] = f"{row['decision_reason']} | {MARKER} {decision} — {reasoning}"
        df.at[idx, "annotation_source"] = f"{row['annotation_source']}+llm_reviewed"
        df.at[idx, "annotation_status"] = "llm_reviewed"
        df.at[idx, "review_decision"] = decision
        # expected_decision is intentionally left untouched.
        # No field is ever set to "human_verified" — this is an LLM-only review.
        updated += 1

    df_csv = df.copy()
    for col in ["resume_text", "job_description_text", "decision_reason"]:
        df_csv[col] = df_csv[col].str.replace("\r\n", "\n", regex=False).str.replace("\n", "\\n", regex=False)
    df_csv.to_csv(csv_path, index=False)

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for _, row in df.iterrows():
            rec = row.to_dict()
            rec["matching_skills"] = [s for s in rec["matching_skills"].split(";") if s]
            rec["missing_skills"] = [s for s in rec["missing_skills"].split(";") if s]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"needs_review rows found this run: {n_needs_review} (curated decisions matched exactly: "
          f"0 missing, 0 unused)")
    print(f"Rows integrated this run: {updated} (0 means already integrated — idempotent)")
    print(f"annotation_status now: {df['annotation_status'].value_counts().to_dict()}")
    print(f"review_decision now: {df.loc[df['review_decision'] != '', 'review_decision'].value_counts().to_dict()}")
    print(f"Columns (must be 15): {len(df.columns)} -> {list(df.columns)}")


if __name__ == "__main__":
    main()
