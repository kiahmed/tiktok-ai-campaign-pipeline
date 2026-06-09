from __future__ import annotations

from sqlalchemy import select

from app.database.models import Product
from app.repositories.base import BaseRepository


class ProductRepository(BaseRepository):
    def list_all(self) -> list[Product]:
        with self._unit_of_work() as session:
            rows = list(session.scalars(select(Product).order_by(Product.created_at.desc())).all())
            for r in rows:
                session.expunge(r)
            return rows

    def create(
        self, *, name: str, slug: str, image_url: str, description: str, benefits: list[str]
    ) -> Product:
        with self._unit_of_work() as session:
            product = Product(
                name=name,
                slug=slug,
                image_url=image_url,
                description=description,
                benefits="\n".join(benefits),
            )
            session.add(product)
            session.flush()
            session.refresh(product)
            session.expunge(product)
            return product

    def get(self, product_id: int) -> Product | None:
        with self._unit_of_work() as session:
            product = session.get(Product, product_id)
            if product is not None:
                session.expunge(product)
            return product
