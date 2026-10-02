from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.wiki import WikiPage


def list_pages(db: Session, user_id: int, project_id: int | None = None) -> list[WikiPage]:
    """列出用户可见的 Wiki 页面。

    project_id 为 None 时返回工作台总 Wiki（全局页），否则返回该项目内的页面。
    """
    query = db.query(WikiPage).filter(WikiPage.user_id == user_id)
    if project_id is None:
        query = query.filter(WikiPage.project_id.is_(None))
    else:
        query = query.filter(WikiPage.project_id == project_id)
    return query.order_by(WikiPage.order.asc(), WikiPage.id.asc()).all()


def get_page(db: Session, user_id: int, page_id: int) -> WikiPage | None:
    return (
        db.query(WikiPage)
        .filter(WikiPage.id == page_id, WikiPage.user_id == user_id)
        .first()
    )


def create_page(
    db: Session,
    user_id: int,
    *,
    title: str,
    content: str = "",
    project_id: int | None = None,
    parent_id: int | None = None,
    is_template: bool = False,
) -> WikiPage:
    siblings = (
        db.query(WikiPage)
        .filter(
            WikiPage.user_id == user_id,
            WikiPage.project_id == project_id,
            WikiPage.parent_id == parent_id,
        )
        .all()
    )
    order = max((p.order for p in siblings), default=-1) + 1
    page = WikiPage(
        user_id=user_id,
        project_id=project_id,
        parent_id=parent_id,
        title=title,
        content=content or f"# {title}\n\n在这里写下内容…",
        is_template=is_template,
        order=order,
    )
    db.add(page)
    db.commit()
    db.refresh(page)
    return page


def update_page(db: Session, page: WikiPage, **fields) -> WikiPage:
    for key, value in fields.items():
        if hasattr(page, key):
            setattr(page, key, value)
    db.commit()
    db.refresh(page)
    return page


def _descendant_ids(db: Session, page_id: int) -> list[int]:
    """递归收集某页的全部后代 id。"""
    direct = [
        p.id
        for p in db.query(WikiPage).filter(WikiPage.parent_id == page_id).all()
    ]
    for child_id in direct:
        direct.extend(_descendant_ids(db, child_id))
    return direct


def delete_page(db: Session, page: WikiPage) -> None:
    ids = [page.id] + _descendant_ids(db, page.id)
    db.query(WikiPage).filter(WikiPage.id.in_(ids)).delete(synchronize_session=False)
    db.commit()


def copy_page_to_project(db: Session, page: WikiPage, target_project_id: int) -> int:
    """把总 Wiki 页面（含全部后代）复制到目标项目，返回复制页数。"""
    pages = [page] + [
        p
        for p in db.query(WikiPage)
        .filter(WikiPage.user_id == page.user_id, WikiPage.project_id.is_(None))
        .all()
        if p.id in _descendant_ids(db, page.id)
    ]

    id_map: dict[int, int] = {}
    order_map: dict[int, int] = {}

    # 复制全部页（先建映射，再回填 parent_id）
    new_pages: list[WikiPage] = []
    for p in pages:
        np = WikiPage(
            user_id=page.user_id,
            project_id=target_project_id,
            parent_id=None,
            title=p.title,
            content=p.content,
            is_template=False,
            order=p.order,
        )
        db.add(np)
        db.flush()
        id_map[p.id] = np.id
        new_pages.append((p, np))

    for src, dst in new_pages:
        dst.parent_id = id_map.get(src.parent_id) if src.parent_id in id_map else None

    db.commit()
    return len(new_pages)
