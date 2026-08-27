import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.product import Product, ProductStatus, ProductVariant


@dataclass(frozen=True)
class VariantSpec:
    """One variant as somebody asked for it, before it is a row.

    A plain value rather than kwargs, because variants arrive in lists --
    from a request body and from a storefront sync -- and a list of
    positional arguments is a list nobody can read.
    """

    external_id: str | None = None
    sku: str | None = None
    title: str | None = None
    price: Decimal | None = None
    stock_quantity: int | None = None
    attributes: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProductWithVariants:
    """A product and everything buyable under it.

    The two are always wanted together -- a price with no sizes is not an
    answer to a customer -- and there are no ORM relationships in this
    application, so the pairing is made explicit here rather than left to
    a lazy load nobody can see in the query log.
    """

    product: Product
    variants: list[ProductVariant]


class ProductRepository:
    """Every query against the catalogue tables lives here.

    Workspace-scoped throughout. This is a business's price list, and a
    query that reached across workspaces would put one shop's margins
    into another shop's customer conversation.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- products ----------------------------------------------------------

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        name: str,
        description: str | None = None,
        status: ProductStatus = ProductStatus.ACTIVE,
        price: Decimal | None = None,
        currency: str | None = None,
        external_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Product:
        product = Product(
            workspace_id=workspace_id,
            name=name,
            description=description,
            status=status,
            price=price,
            currency=currency,
            external_id=external_id,
            meta=meta or {},
        )

        self._session.add(product)
        self._session.flush()

        return product

    def get(
        self,
        workspace_id: uuid.UUID,
        product_id: uuid.UUID,
    ) -> Product | None:
        return self._session.scalar(
            select(Product).where(
                Product.id == product_id,
                Product.workspace_id == workspace_id,
            )
        )

    def get_by_external_id(
        self,
        workspace_id: uuid.UUID,
        external_id: str,
    ) -> Product | None:
        """The lookup a storefront sync re-runs against.

        Unique per workspace, so re-importing a catalogue updates it
        rather than doubling it.
        """
        return self._session.scalar(
            select(Product).where(
                Product.workspace_id == workspace_id,
                Product.external_id == external_id,
            )
        )

    def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        search: str | None = None,
        status: ProductStatus | None = None,
        in_stock: bool | None = None,
    ) -> Sequence[Product]:
        statement = self._filtered(
            select(Product),
            workspace_id,
            search=search,
            status=status,
            in_stock=in_stock,
        )

        return self._session.scalars(
            statement.order_by(Product.created_at.desc(), Product.id)
            .limit(limit)
            .offset(offset)
        ).all()

    def count_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        search: str | None = None,
        status: ProductStatus | None = None,
        in_stock: bool | None = None,
    ) -> int:
        statement = self._filtered(
            select(func.count()).select_from(Product),
            workspace_id,
            search=search,
            status=status,
            in_stock=in_stock,
        )

        return self._session.scalar(statement) or 0

    def update(
        self,
        product: Product,
        *,
        name: str | None = None,
        description: str | None = None,
        status: ProductStatus | None = None,
        price: Decimal | None = None,
        currency: str | None = None,
        external_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Product:
        """Apply what was supplied and leave the rest alone.

        `None` means "no change" here, as it does in every other
        repository. Clearing a price back to null is therefore not
        something this expresses -- a product whose price is being removed
        rather than changed is rare enough that inventing a sentinel for
        it would cost more clarity than it buys.
        """
        if name is not None:
            product.name = name

        if description is not None:
            product.description = description

        if status is not None:
            product.status = status

        if price is not None:
            product.price = price

        if currency is not None:
            product.currency = currency

        if external_id is not None:
            product.external_id = external_id

        if meta is not None:
            product.meta = meta

        self._session.flush()

        return product

    def delete(self, product: Product) -> None:
        # The variants go with it, through the composite foreign key's
        # ON DELETE CASCADE.
        self._session.delete(product)
        self._session.flush()

    # --- variants ----------------------------------------------------------

    def replace_variants(
        self,
        workspace_id: uuid.UUID,
        product: Product,
        specs: Iterable[VariantSpec],
    ) -> list[ProductVariant]:
        """Make the product's variants exactly these, in this order.

        Replaced wholesale rather than merged. A merge needs a rule for
        matching an incoming variant to an existing row, and the only
        honest rule -- match on external_id or sku -- says nothing about
        the hand-entered variants that have neither. Nothing references a
        variant by id yet, so replacing them costs nothing; the day an
        order line does, this becomes an upsert and the rule is external
        id.
        """
        for existing in self.variants_for(workspace_id, [product.id]).get(
            product.id, []
        ):
            self._session.delete(existing)

        # Before the inserts, or the unique constraint on sku fires
        # against rows that are on their way out.
        self._session.flush()

        created = [
            ProductVariant(
                workspace_id=workspace_id,
                product_id=product.id,
                external_id=spec.external_id,
                sku=spec.sku,
                title=spec.title,
                price=spec.price,
                stock_quantity=spec.stock_quantity,
                attributes=spec.attributes or {},
            )
            for spec in specs
        ]

        self._session.add_all(created)
        self._session.flush()

        return created

    def variants_for(
        self,
        workspace_id: uuid.UUID,
        product_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, list[ProductVariant]]:
        """Every variant of these products, grouped by product.

        One query for a whole page. Asking per product would be a query
        per row of a list endpoint, which is the classic way a catalogue
        page gets slow the week a customer uploads a real one.
        """
        if not product_ids:
            return {}

        rows = self._session.scalars(
            select(ProductVariant)
            .where(
                ProductVariant.workspace_id == workspace_id,
                ProductVariant.product_id.in_(product_ids),
            )
            .order_by(ProductVariant.created_at, ProductVariant.id)
        ).all()

        grouped: dict[uuid.UUID, list[ProductVariant]] = {}

        for variant in rows:
            grouped.setdefault(variant.product_id, []).append(variant)

        return grouped

    def with_variants(
        self,
        workspace_id: uuid.UUID,
        products: Sequence[Product],
    ) -> list[ProductWithVariants]:
        grouped = self.variants_for(workspace_id, [product.id for product in products])

        return [
            ProductWithVariants(product=product, variants=grouped.get(product.id, []))
            for product in products
        ]

    # --- the lookup the assistant uses -------------------------------------

    def search(
        self,
        workspace_id: uuid.UUID,
        terms: Sequence[str],
        *,
        limit: int,
    ) -> Sequence[Product]:
        """Active products matching any of these words.

        The structured half of what the plan asks for. A customer asking
        "do you have the black hoodie in medium" gets a row with a price
        and a stock level, looked up rather than recalled -- which is the
        difference between an answer and a plausible sentence.

        Deliberately only `active`: a draft is something the business has
        not decided to sell, and offering it is worse than saying nothing.
        """
        words = [word for word in terms if len(word) >= 3]

        if not words:
            return []

        return self._session.scalars(
            select(Product)
            .where(
                Product.workspace_id == workspace_id,
                Product.status == ProductStatus.ACTIVE,
                or_(*(self._mentions(word) for word in words)),
            )
            .order_by(Product.name, Product.id)
            .limit(limit)
        ).all()

    # --- shared ------------------------------------------------------------

    def _filtered(
        self,
        statement: Select[Any],
        workspace_id: uuid.UUID,
        *,
        search: str | None,
        status: ProductStatus | None,
        in_stock: bool | None,
    ) -> Select[Any]:
        statement = statement.where(Product.workspace_id == workspace_id)

        if search:
            statement = statement.where(self._mentions(search))

        if status is not None:
            statement = statement.where(Product.status == status)

        if in_stock is not None:
            # "In stock" means a variant that is counted and positive.
            # "Out of stock" is not its negation: a product whose stock
            # nobody tracks is neither, and it has to fall out of both
            # answers rather than be reported as unavailable. So `false`
            # asks for products that *are* counted and have nothing left.
            available = self._variants_where(ProductVariant.stock_quantity > 0)

            if in_stock:
                statement = statement.where(available.exists())
            else:
                counted = self._variants_where(
                    ProductVariant.stock_quantity.is_not(None)
                )
                statement = statement.where(counted.exists(), ~available.exists())

        return statement

    def _variants_where(self, condition: ColumnElement[bool]) -> Select[Any]:
        """This product's variants, filtered -- correlated to the outer row."""
        return select(ProductVariant.id).where(
            ProductVariant.workspace_id == Product.workspace_id,
            ProductVariant.product_id == Product.id,
            condition,
        )

    def _mentions(self, term: str) -> ColumnElement[bool]:
        """Name, description, or the SKU of one of its variants.

        A SKU because a customer quoting one back is quoting the only
        identifier they were given, and a search that could not find it
        would fail on the most precise question anybody asks.
        """
        pattern = f"%{term}%"

        return or_(
            Product.name.ilike(pattern),
            Product.description.ilike(pattern),
            select(ProductVariant.id)
            .where(
                and_(
                    ProductVariant.workspace_id == Product.workspace_id,
                    ProductVariant.product_id == Product.id,
                    ProductVariant.sku.ilike(pattern),
                )
            )
            .exists(),
        )
