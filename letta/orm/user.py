from sqlalchemy.orm import Mapped, mapped_column, relationship

from letta.orm.mixins import OrganizationMixin
from letta.orm.organization import Organization
from letta.orm.sqlalchemy_base import SqlalchemyBase
from letta.schemas.user import User as PydanticUser


class User(SqlalchemyBase, OrganizationMixin):
    """User ORM class"""

    __tablename__ = "user"
    __pydantic_model__ = PydanticUser

    name: Mapped[str] = mapped_column(nullable=False, doc="The display name of the user.")

    # relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="users")

    # TODO: Add this back later potentially
    # agents: Mapped[List["Agent"]] = relationship(
    #     "Agent", secondary="users_agents", back_populates="users", doc="the agents associated with this user."
    # )
    # tokens: Mapped[List["Token"]] = relationship("Token", back_populates="user", doc="the tokens associated with this user.")
    # jobs: Mapped[List["Job"]] = relationship("Job", back_populates="user", doc="the jobs associated with this user.")
