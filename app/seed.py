"""Idempotent seed script: diagnostic centres, tests, and centre-test pricing.

Run with:  python -m app.seed
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.diagnostic import CentreTest, DiagnosticCentre, DiagnosticTest

logger = logging.getLogger("eve.seed")

CENTRES = [
    {
        "name": "CityCare Diagnostics",
        "address": "12 MG Road, Sector 4",
        "city": "Bengaluru",
        "prices": {"CBC": 350.00, "LFT": 800.00, "KFT": 750.00, "THYROID": 600.00, "VITD": 1200.00},
    },
    {
        "name": "Apollo Wellness Labs",
        "address": "48 Park Street",
        "city": "Kolkata",
        "prices": {"CBC": 300.00, "LFT": 700.00, "GLUF": 150.00, "THYROID": 550.00},
    },
]

TESTS = [
    ("CBC", "Complete Blood Count", "Screens for anaemia, infections, and blood disorders."),
    ("LFT", "Liver Function Test", "Measures liver enzymes, proteins, and bilirubin."),
    ("KFT", "Kidney Function Test", "Evaluates creatinine, urea, and electrolyte levels."),
    ("THYROID", "Thyroid Profile (TSH, T3, T4)", "Assesses thyroid gland function."),
    ("VITD", "Vitamin D (25-OH)", "Measures vitamin D levels in blood."),
    ("GLUF", "Fasting Blood Glucose", "Screens for diabetes and prediabetes."),
]


def seed() -> None:
    db: Session = SessionLocal()
    try:
        tests_by_code: dict[str, DiagnosticTest] = {}
        for code, name, description in TESTS:
            test = db.execute(
                select(DiagnosticTest).where(DiagnosticTest.code == code)
            ).scalar_one_or_none()
            if test is None:
                test = DiagnosticTest(code=code, name=name, description=description)
                db.add(test)
                logger.info("created test %s", code)
            tests_by_code[code] = test

        for spec in CENTRES:
            centre = db.execute(
                select(DiagnosticCentre).where(
                    DiagnosticCentre.name == spec["name"], DiagnosticCentre.city == spec["city"]
                )
            ).scalar_one_or_none()
            if centre is None:
                centre = DiagnosticCentre(
                    name=spec["name"], address=spec["address"], city=spec["city"]
                )
                db.add(centre)
                db.flush()
                logger.info("created centre %s", spec["name"])

            for code, price in spec["prices"].items():
                test = tests_by_code[code]
                existing = db.execute(
                    select(CentreTest).where(
                        CentreTest.centre_id == centre.id, CentreTest.test_id == test.id
                    )
                ).scalar_one_or_none()
                if existing is None:
                    db.add(CentreTest(centre_id=centre.id, test_id=test.id, price=price))
                    logger.info("priced %s at %s: %.2f", code, spec["name"], price)

        db.commit()
        logger.info("seed complete")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    seed()
