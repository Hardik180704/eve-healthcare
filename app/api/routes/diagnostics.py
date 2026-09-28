from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.models.diagnostic import CentreTest, DiagnosticCentre, DiagnosticTest
from app.models.user import User
from app.schemas.diagnostic import (
    CentreCreate,
    CentreOut,
    CentreTestCreate,
    CentreWithTests,
    TestCreate,
    TestOut,
    TestWithPrice,
)


def _test_with_price(centre_test: CentreTest) -> TestWithPrice:
    return TestWithPrice(
        id=centre_test.test.id,
        code=centre_test.test.code,
        name=centre_test.test.name,
        description=centre_test.test.description,
        price=centre_test.price,
    )


router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


# --- Diagnostic centres ---


@router.post("/centres", response_model=CentreOut, status_code=201, summary="Create a centre")
def create_centre(
    payload: CentreCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    centre = DiagnosticCentre(**payload.model_dump())
    db.add(centre)
    db.commit()
    db.refresh(centre)
    return centre


@router.get("/centres", response_model=list[CentreOut], summary="List all centres")
def list_centres(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return db.scalars(select(DiagnosticCentre).order_by(DiagnosticCentre.id)).all()


@router.get(
    "/centres/{centre_id}",
    response_model=CentreWithTests,
    summary="Get a centre with its offered tests and prices",
)
def get_centre(
    centre_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    centre = db.get(DiagnosticCentre, centre_id)
    if centre is None:
        raise NotFoundError("Diagnostic centre not found")
    centre_tests = db.scalars(
        select(CentreTest).where(CentreTest.centre_id == centre_id).order_by(CentreTest.test_id)
    ).all()
    tests = [_test_with_price(ct) for ct in centre_tests]
    return CentreWithTests(
        id=centre.id,
        name=centre.name,
        address=centre.address,
        city=centre.city,
        created_at=centre.created_at,
        tests=tests,
    )


@router.post(
    "/centres/{centre_id}/tests",
    response_model=TestWithPrice,
    status_code=201,
    summary="Offer a test at a centre with centre-specific pricing",
)
def add_test_to_centre(
    centre_id: int,
    payload: CentreTestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    centre = db.get(DiagnosticCentre, centre_id)
    if centre is None:
        raise NotFoundError("Diagnostic centre not found")
    test = db.get(DiagnosticTest, payload.test_id)
    if test is None:
        raise NotFoundError("Diagnostic test not found")

    existing = db.execute(
        select(CentreTest).where(
            CentreTest.centre_id == centre_id, CentreTest.test_id == payload.test_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("This test is already offered at this centre")

    centre_test = CentreTest(centre_id=centre_id, test_id=payload.test_id, price=payload.price)
    db.add(centre_test)
    db.commit()
    db.refresh(centre_test)
    return _test_with_price(centre_test)


@router.get(
    "/centres/{centre_id}/tests",
    response_model=list[TestWithPrice],
    summary="List tests offered at a centre with prices",
)
def list_centre_tests(
    centre_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    centre = db.get(DiagnosticCentre, centre_id)
    if centre is None:
        raise NotFoundError("Diagnostic centre not found")
    centre_tests = db.scalars(
        select(CentreTest).where(CentreTest.centre_id == centre_id).order_by(CentreTest.test_id)
    ).all()
    return [_test_with_price(ct) for ct in centre_tests]


# --- Diagnostic tests ---


@router.post("/tests", response_model=TestOut, status_code=201, summary="Create a test")
def create_test(
    payload: TestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    code = payload.code.strip().upper()
    existing = db.execute(
        select(DiagnosticTest).where(DiagnosticTest.code == code)
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("A test with this code already exists")

    test = DiagnosticTest(code=code, name=payload.name.strip(), description=payload.description)
    db.add(test)
    db.commit()
    db.refresh(test)
    return test


@router.get("/tests", response_model=list[TestOut], summary="List all tests")
def list_tests(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return db.scalars(select(DiagnosticTest).order_by(DiagnosticTest.id)).all()
