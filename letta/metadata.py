""" Metadata store for user/agent/data_source information"""

import os
import secrets
from typing import List, Optional

from sqlalchemy import (
    BIGINT,
    JSON,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    TypeDecorator,
    asc,
    or_,
)
from sqlalchemy.sql import func

from letta.config import LettaConfig
from letta.orm.base import Base
from letta.schemas.agent import AgentState
from letta.schemas.api_key import APIKey
from letta.schemas.block import Block, Human, Persona
from letta.schemas.embedding_config import EmbeddingConfig
from letta.schemas.enums import JobStatus
from letta.schemas.file import FileMetadata
from letta.schemas.job import Job
from letta.schemas.llm_config import LLMConfig
from letta.schemas.memory import Memory
from letta.schemas.openai.chat_completions import ToolCall, ToolCallFunction
from letta.schemas.source import Source
from letta.schemas.tool import Tool
from letta.schemas.user import User
from letta.settings import settings
from letta.utils import enforce_types, get_utc_time, printd


class FileMetadataModel(Base):
    __tablename__ = "files"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, nullable=False)
    user_id = Column(String, nullable=False)
    # TODO: Investigate why this breaks during table creation due to FK
    # source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    source_id = Column(String, nullable=False)
    file_name = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    file_type = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    file_creation_date = Column(String, nullable=True)
    file_last_modified_date = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<FileMetadata(id='{self.id}', source_id='{self.source_id}', file_name='{self.file_name}')>"

    def to_record(self):
        return FileMetadata(
            id=self.id,
            user_id=self.user_id,
            source_id=self.source_id,
            file_name=self.file_name,
            file_path=self.file_path,
            file_type=self.file_type,
            file_size=self.file_size,
            file_creation_date=self.file_creation_date,
            file_last_modified_date=self.file_last_modified_date,
            created_at=self.created_at,
        )


class LLMConfigColumn(TypeDecorator):
    """Custom type for storing LLMConfig as JSON"""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value:
            # return vars(value)
            if isinstance(value, LLMConfig):
                return value.model_dump()
        return value

    def process_result_value(self, value, dialect):
        if value:
            return LLMConfig(**value)
        return value


class EmbeddingConfigColumn(TypeDecorator):
    """Custom type for storing EmbeddingConfig as JSON"""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value:
            # return vars(value)
            if isinstance(value, EmbeddingConfig):
                return value.model_dump()
        return value

    def process_result_value(self, value, dialect):
        if value:
            return EmbeddingConfig(**value)
        return value


class ToolCallColumn(TypeDecorator):

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value:
            values = []
            for v in value:
                if isinstance(v, ToolCall):
                    values.append(v.model_dump())
                else:
                    values.append(v)
            return values

        return value

    def process_result_value(self, value, dialect):
        if value:
            tools = []
            for tool_value in value:
                if "function" in tool_value:
                    tool_call_function = ToolCallFunction(**tool_value["function"])
                    del tool_value["function"]
                else:
                    tool_call_function = None
                tools.append(ToolCall(function=tool_call_function, **tool_value))
            return tools
        return value


# TODO: eventually store providers?
# class Provider(Base):
#    __tablename__ = "providers"
#    __table_args__ = {"extend_existing": True}
#
#    id = Column(String, primary_key=True)
#    name = Column(String, nullable=False)
#    created_at = Column(DateTime(timezone=True))
#    api_key = Column(String, nullable=False)
#    base_url = Column(String, nullable=False)


class APIKeyModel(Base):
    """Data model for authentication tokens. One-to-many relationship with UserModel (1 User - N tokens)."""

    __tablename__ = "tokens"

    id = Column(String, primary_key=True)
    # each api key is tied to a user account (that it validates access for)
    user_id = Column(String, nullable=False)
    # the api key
    key = Column(String, nullable=False)
    # extra (optional) metadata
    name = Column(String)

    Index(__tablename__ + "_idx_user", user_id),
    Index(__tablename__ + "_idx_key", key),

    def __repr__(self) -> str:
        return f"<APIKey(id='{self.id}', key='{self.key}', name='{self.name}')>"

    def to_record(self) -> User:
        return APIKey(
            id=self.id,
            user_id=self.user_id,
            key=self.key,
            name=self.name,
        )


def generate_api_key(prefix="sk-", length=51) -> str:
    # Generate 'length // 2' bytes because each byte becomes two hex digits. Adjust length for prefix.
    actual_length = max(length - len(prefix), 1) // 2  # Ensure at least 1 byte is generated
    random_bytes = secrets.token_bytes(actual_length)
    new_key = prefix + random_bytes.hex()
    return new_key


class AgentModel(Base):
    """Defines data model for storing Passages (consisting of text, embedding)"""

    __tablename__ = "agents"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    description = Column(String)

    # state (context compilation)
    message_ids = Column(JSON)
    memory = Column(JSON)
    system = Column(String)
    tools = Column(JSON)

    # configs
    agent_type = Column(String)
    llm_config = Column(LLMConfigColumn)
    embedding_config = Column(EmbeddingConfigColumn)

    # state
    metadata_ = Column(JSON)

    # tools
    tools = Column(JSON)

    Index(__tablename__ + "_idx_user", user_id),

    def __repr__(self) -> str:
        return f"<Agent(id='{self.id}', name='{self.name}')>"

    def to_record(self) -> AgentState:
        agent_state = AgentState(
            id=self.id,
            user_id=self.user_id,
            name=self.name,
            created_at=self.created_at,
            description=self.description,
            message_ids=self.message_ids,
            memory=Memory.load(self.memory),  # load dictionary
            system=self.system,
            tools=self.tools,
            agent_type=self.agent_type,
            llm_config=self.llm_config,
            embedding_config=self.embedding_config,
            metadata_=self.metadata_,
        )
        assert isinstance(agent_state.memory, Memory), f"Memory object is not of type Memory: {type(agent_state.memory)}"
        return agent_state


class SourceModel(Base):
    """Defines data model for storing Passages (consisting of text, embedding)"""

    __tablename__ = "sources"
    __table_args__ = {"extend_existing": True}

    # Assuming passage_id is the primary key
    # id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    embedding_config = Column(EmbeddingConfigColumn)
    description = Column(String)
    metadata_ = Column(JSON)
    Index(__tablename__ + "_idx_user", user_id),

    # TODO: add num passages

    def __repr__(self) -> str:
        return f"<Source(passage_id='{self.id}', name='{self.name}')>"

    def to_record(self) -> Source:
        return Source(
            id=self.id,
            user_id=self.user_id,
            name=self.name,
            created_at=self.created_at,
            embedding_config=self.embedding_config,
            description=self.description,
            metadata_=self.metadata_,
        )


class AgentSourceMappingModel(Base):
    """Stores mapping between agent -> source"""

    __tablename__ = "agent_source_mapping"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    agent_id = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    Index(__tablename__ + "_idx_user", user_id, agent_id, source_id),

    def __repr__(self) -> str:
        return f"<AgentSourceMapping(user_id='{self.user_id}', agent_id='{self.agent_id}', source_id='{self.source_id}')>"


class BlockModel(Base):
    __tablename__ = "block"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, nullable=False)
    value = Column(String, nullable=False)
    limit = Column(BIGINT)
    name = Column(String, nullable=False)
    template = Column(Boolean, default=False)  # True: listed as possible human/persona
    label = Column(String)
    metadata_ = Column(JSON)
    description = Column(String)
    user_id = Column(String)
    Index(__tablename__ + "_idx_user", user_id),

    def __repr__(self) -> str:
        return f"<Block(id='{self.id}', name='{self.name}', template='{self.template}', label='{self.label}', user_id='{self.user_id}')>"

    def to_record(self) -> Block:
        if self.label == "persona":
            return Persona(
                id=self.id,
                value=self.value,
                limit=self.limit,
                name=self.name,
                template=self.template,
                label=self.label,
                metadata_=self.metadata_,
                description=self.description,
                user_id=self.user_id,
            )
        elif self.label == "human":
            return Human(
                id=self.id,
                value=self.value,
                limit=self.limit,
                name=self.name,
                template=self.template,
                label=self.label,
                metadata_=self.metadata_,
                description=self.description,
                user_id=self.user_id,
            )
        else:
            return Block(
                id=self.id,
                value=self.value,
                limit=self.limit,
                name=self.name,
                template=self.template,
                label=self.label,
                metadata_=self.metadata_,
                description=self.description,
                user_id=self.user_id,
            )


class ToolModel(Base):
    __tablename__ = "tools"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    user_id = Column(String)
    description = Column(String)
    source_type = Column(String)
    source_code = Column(String)
    json_schema = Column(JSON)
    module = Column(String)
    tags = Column(JSON)

    def __repr__(self) -> str:
        return f"<Tool(id='{self.id}', name='{self.name}')>"

    def to_record(self) -> Tool:
        return Tool(
            id=self.id,
            name=self.name,
            user_id=self.user_id,
            description=self.description,
            source_type=self.source_type,
            source_code=self.source_code,
            json_schema=self.json_schema,
            module=self.module,
            tags=self.tags,
        )


class JobModel(Base):
    __tablename__ = "jobs"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True)
    user_id = Column(String)
    status = Column(String, default=JobStatus.pending)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), onupdate=func.now())
    metadata_ = Column(JSON)

    def __repr__(self) -> str:
        return f"<Job(id='{self.id}', status='{self.status}')>"

    def to_record(self):
        return Job(
            id=self.id,
            user_id=self.user_id,
            status=self.status,
            created_at=self.created_at,
            completed_at=self.completed_at,
            metadata_=self.metadata_,
        )


class MetadataStore:
    uri: Optional[str] = None

    def __init__(self, config: LettaConfig):
        # TODO: get DB URI or path
        if config.metadata_storage_type == "postgres":
            # construct URI from enviornment variables
            self.uri = settings.pg_uri if settings.pg_uri else config.metadata_storage_uri

        elif config.metadata_storage_type == "sqlite":
            path = os.path.join(config.metadata_storage_path, "sqlite.db")
            self.uri = f"sqlite:///{path}"
        else:
            raise ValueError(f"Invalid metadata storage type: {config.metadata_storage_type}")

        # Ensure valid URI
        assert self.uri, "Database URI is not provided or is invalid."

        from letta.server.server import db_context

        self.session_maker = db_context

    @enforce_types
    def create_api_key(self, user_id: str, name: str) -> APIKey:
        """Create an API key for a user"""
        new_api_key = generate_api_key()
        with self.session_maker() as session:
            if session.query(APIKeyModel).filter(APIKeyModel.key == new_api_key).count() > 0:
                # NOTE duplicate API keys / tokens should never happen, but if it does don't allow it
                raise ValueError(f"Token {new_api_key} already exists")
            # TODO store the API keys as hashed
            assert user_id and name, "User ID and name must be provided"
            token = APIKey(user_id=user_id, key=new_api_key, name=name)
            session.add(APIKeyModel(**vars(token)))
            session.commit()
        return self.get_api_key(api_key=new_api_key)

    @enforce_types
    def delete_api_key(self, api_key: str):
        """Delete an API key from the database"""
        with self.session_maker() as session:
            session.query(APIKeyModel).filter(APIKeyModel.key == api_key).delete()
            session.commit()

    @enforce_types
    def get_api_key(self, api_key: str) -> Optional[APIKey]:
        with self.session_maker() as session:
            results = session.query(APIKeyModel).filter(APIKeyModel.key == api_key).all()
            if len(results) == 0:
                return None
            assert len(results) == 1, f"Expected 1 result, got {len(results)}"  # should only be one result
            return results[0].to_record()

    @enforce_types
    def get_all_api_keys_for_user(self, user_id: str) -> List[APIKey]:
        with self.session_maker() as session:
            results = session.query(APIKeyModel).filter(APIKeyModel.user_id == user_id).all()
            tokens = [r.to_record() for r in results]
            return tokens

    @enforce_types
    def create_agent(self, agent: AgentState):
        # insert into agent table
        # make sure agent.name does not already exist for user user_id
        with self.session_maker() as session:
            if session.query(AgentModel).filter(AgentModel.name == agent.name).filter(AgentModel.user_id == agent.user_id).count() > 0:
                raise ValueError(f"Agent with name {agent.name} already exists")
            fields = vars(agent)
            fields["memory"] = agent.memory.to_dict()
            del fields["_internal_memory"]
            session.add(AgentModel(**fields))
            session.commit()

    @enforce_types
    def create_source(self, source: Source):
        with self.session_maker() as session:
            if session.query(SourceModel).filter(SourceModel.name == source.name).filter(SourceModel.user_id == source.user_id).count() > 0:
                raise ValueError(f"Source with name {source.name} already exists for user {source.user_id}")
            session.add(SourceModel(**vars(source)))
            session.commit()

    @enforce_types
    def create_block(self, block: Block):
        with self.session_maker() as session:
            # TODO: fix?
            # we are only validating that more than one template block
            # with a given name doesn't exist.
            if (
                session.query(BlockModel)
                .filter(BlockModel.name == block.name)
                .filter(BlockModel.user_id == block.user_id)
                .filter(BlockModel.template == True)
                .filter(BlockModel.label == block.label)
                .count()
                > 0
            ):

                raise ValueError(f"Block with name {block.name} already exists")
            session.add(BlockModel(**vars(block)))
            session.commit()

    @enforce_types
    def create_tool(self, tool: Tool):
        with self.session_maker() as session:
            if self.get_tool(tool_id=tool.id, tool_name=tool.name, user_id=tool.user_id) is not None:
                raise ValueError(f"Tool with name {tool.name} already exists")
            session.add(ToolModel(**vars(tool)))
            session.commit()

    @enforce_types
    def update_agent(self, agent: AgentState):
        with self.session_maker() as session:
            fields = vars(agent)
            if isinstance(agent.memory, Memory):  # TODO: this is nasty but this whole class will soon be removed so whatever
                fields["memory"] = agent.memory.to_dict()
            del fields["_internal_memory"]
            session.query(AgentModel).filter(AgentModel.id == agent.id).update(fields)
            session.commit()

    @enforce_types
    def update_source(self, source: Source):
        with self.session_maker() as session:
            session.query(SourceModel).filter(SourceModel.id == source.id).update(vars(source))
            session.commit()

    @enforce_types
    def update_block(self, block: Block):
        with self.session_maker() as session:
            session.query(BlockModel).filter(BlockModel.id == block.id).update(vars(block))
            session.commit()

    @enforce_types
    def update_or_create_block(self, block: Block):
        with self.session_maker() as session:
            existing_block = session.query(BlockModel).filter(BlockModel.id == block.id).first()
            if existing_block:
                session.query(BlockModel).filter(BlockModel.id == block.id).update(vars(block))
            else:
                session.add(BlockModel(**vars(block)))
            session.commit()

    @enforce_types
    def update_tool(self, tool_id: str, tool: Tool):
        with self.session_maker() as session:
            session.query(ToolModel).filter(ToolModel.id == tool_id).update(vars(tool))
            session.commit()

    @enforce_types
    def delete_tool(self, tool_id: str):
        with self.session_maker() as session:
            session.query(ToolModel).filter(ToolModel.id == tool_id).delete()
            session.commit()

    @enforce_types
    def delete_file_from_source(self, source_id: str, file_id: str, user_id: Optional[str]):
        with self.session_maker() as session:
            file_metadata = (
                session.query(FileMetadataModel)
                .filter(FileMetadataModel.source_id == source_id, FileMetadataModel.id == file_id, FileMetadataModel.user_id == user_id)
                .first()
            )

            if file_metadata:
                session.delete(file_metadata)
                session.commit()

            return file_metadata

    @enforce_types
    def delete_block(self, block_id: str):
        with self.session_maker() as session:
            session.query(BlockModel).filter(BlockModel.id == block_id).delete()
            session.commit()

    @enforce_types
    def delete_agent(self, agent_id: str):
        with self.session_maker() as session:

            # delete agents
            session.query(AgentModel).filter(AgentModel.id == agent_id).delete()

            # delete mappings
            session.query(AgentSourceMappingModel).filter(AgentSourceMappingModel.agent_id == agent_id).delete()

            session.commit()

    @enforce_types
    def delete_source(self, source_id: str):
        with self.session_maker() as session:
            # delete from sources table
            session.query(SourceModel).filter(SourceModel.id == source_id).delete()

            # delete any mappings
            session.query(AgentSourceMappingModel).filter(AgentSourceMappingModel.source_id == source_id).delete()

            session.commit()

    @enforce_types
    def list_tools(self, cursor: Optional[str] = None, limit: Optional[int] = 50, user_id: Optional[str] = None) -> List[ToolModel]:
        with self.session_maker() as session:
            # Query for public tools or user-specific tools
            query = session.query(ToolModel).filter(or_(ToolModel.user_id == None, ToolModel.user_id == user_id))

            # Apply cursor if provided (assuming cursor is an ID)
            if cursor:
                query = query.filter(ToolModel.id > cursor)

            # Order by ID and apply limit
            results = query.order_by(asc(ToolModel.id)).limit(limit).all()

            # Convert to records
            res = [r.to_record() for r in results]
            return res

    @enforce_types
    def list_agents(self, user_id: str) -> List[AgentState]:
        with self.session_maker() as session:
            results = session.query(AgentModel).filter(AgentModel.user_id == user_id).all()
            return [r.to_record() for r in results]

    @enforce_types
    def list_sources(self, user_id: str) -> List[Source]:
        with self.session_maker() as session:
            results = session.query(SourceModel).filter(SourceModel.user_id == user_id).all()
            return [r.to_record() for r in results]

    @enforce_types
    def get_agent(
        self, agent_id: Optional[str] = None, agent_name: Optional[str] = None, user_id: Optional[str] = None
    ) -> Optional[AgentState]:
        with self.session_maker() as session:
            if agent_id:
                results = session.query(AgentModel).filter(AgentModel.id == agent_id).all()
            else:
                assert agent_name is not None and user_id is not None, "Must provide either agent_id or agent_name"
                results = session.query(AgentModel).filter(AgentModel.name == agent_name).filter(AgentModel.user_id == user_id).all()

            if len(results) == 0:
                return None
            assert len(results) == 1, f"Expected 1 result, got {len(results)}"  # should only be one result
            return results[0].to_record()

    @enforce_types
    def get_source(
        self, source_id: Optional[str] = None, user_id: Optional[str] = None, source_name: Optional[str] = None
    ) -> Optional[Source]:
        with self.session_maker() as session:
            if source_id:
                results = session.query(SourceModel).filter(SourceModel.id == source_id).all()
            else:
                assert user_id is not None and source_name is not None
                results = session.query(SourceModel).filter(SourceModel.name == source_name).filter(SourceModel.user_id == user_id).all()
            if len(results) == 0:
                return None
            assert len(results) == 1, f"Expected 1 result, got {len(results)}"
            return results[0].to_record()

    @enforce_types
    def get_tool(
        self, tool_name: Optional[str] = None, tool_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> Optional[ToolModel]:
        with self.session_maker() as session:
            if tool_id:
                results = session.query(ToolModel).filter(ToolModel.id == tool_id).all()
            else:
                assert tool_name is not None
                results = session.query(ToolModel).filter(ToolModel.name == tool_name).filter(ToolModel.user_id == None).all()
                if user_id:
                    results += session.query(ToolModel).filter(ToolModel.name == tool_name).filter(ToolModel.user_id == user_id).all()
            if len(results) == 0:
                return None
            # assert len(results) == 1, f"Expected 1 result, got {len(results)}"
            return results[0].to_record()

    @enforce_types
    def get_tool_with_name_and_user_id(self, tool_name: Optional[str] = None, user_id: Optional[str] = None) -> Optional[ToolModel]:
        with self.session_maker() as session:
            results = session.query(ToolModel).filter(ToolModel.name == tool_name).filter(ToolModel.user_id == user_id).all()
            if len(results) == 0:
                return None
            assert len(results) == 1, f"Expected 1 result, got {len(results)}"
            return results[0].to_record()

    @enforce_types
    def get_block(self, block_id: str) -> Optional[Block]:
        with self.session_maker() as session:
            results = session.query(BlockModel).filter(BlockModel.id == block_id).all()
            if len(results) == 0:
                return None
            assert len(results) == 1, f"Expected 1 result, got {len(results)}"
            return results[0].to_record()

    @enforce_types
    def get_blocks(
        self,
        user_id: Optional[str],
        label: Optional[str] = None,
        template: Optional[bool] = None,
        name: Optional[str] = None,
        id: Optional[str] = None,
    ) -> Optional[List[Block]]:
        """List available blocks"""
        with self.session_maker() as session:
            query = session.query(BlockModel)

            if user_id:
                query = query.filter(BlockModel.user_id == user_id)

            if label:
                query = query.filter(BlockModel.label == label)

            if name:
                query = query.filter(BlockModel.name == name)

            if id:
                query = query.filter(BlockModel.id == id)

            if template:
                query = query.filter(BlockModel.template == template)

            results = query.all()

            if len(results) == 0:
                return None

            return [r.to_record() for r in results]

    # agent source metadata
    @enforce_types
    def attach_source(self, user_id: str, agent_id: str, source_id: str):
        with self.session_maker() as session:
            # TODO: remove this (is a hack)
            mapping_id = f"{user_id}-{agent_id}-{source_id}"
            session.add(AgentSourceMappingModel(id=mapping_id, user_id=user_id, agent_id=agent_id, source_id=source_id))
            session.commit()

    @enforce_types
    def list_attached_sources(self, agent_id: str) -> List[Source]:
        with self.session_maker() as session:
            results = session.query(AgentSourceMappingModel).filter(AgentSourceMappingModel.agent_id == agent_id).all()

            sources = []
            # make sure source exists
            for r in results:
                source = self.get_source(source_id=r.source_id)
                if source:
                    sources.append(source)
                else:
                    printd(f"Warning: source {r.source_id} does not exist but exists in mapping database. This should never happen.")
            return sources

    @enforce_types
    def list_attached_agents(self, source_id: str) -> List[str]:
        with self.session_maker() as session:
            results = session.query(AgentSourceMappingModel).filter(AgentSourceMappingModel.source_id == source_id).all()

            agent_ids = []
            # make sure agent exists
            for r in results:
                agent = self.get_agent(agent_id=r.agent_id)
                if agent:
                    agent_ids.append(r.agent_id)
                else:
                    printd(f"Warning: agent {r.agent_id} does not exist but exists in mapping database. This should never happen.")
            return agent_ids

    @enforce_types
    def detach_source(self, agent_id: str, source_id: str):
        with self.session_maker() as session:
            session.query(AgentSourceMappingModel).filter(
                AgentSourceMappingModel.agent_id == agent_id, AgentSourceMappingModel.source_id == source_id
            ).delete()
            session.commit()

    @enforce_types
    def create_job(self, job: Job):
        with self.session_maker() as session:
            session.add(JobModel(**vars(job)))
            session.commit()

    @enforce_types
    def list_files_from_source(self, source_id: str, limit: int, cursor: Optional[str]):
        with self.session_maker() as session:
            # Start with the basic query filtered by source_id
            query = session.query(FileMetadataModel).filter(FileMetadataModel.source_id == source_id)

            if cursor:
                # Assuming cursor is the ID of the last file in the previous page
                query = query.filter(FileMetadataModel.id > cursor)

            # Order by ID or other ordering criteria to ensure correct pagination
            query = query.order_by(FileMetadataModel.id)

            # Limit the number of results returned
            results = query.limit(limit).all()

            # Convert the results to the required FileMetadata objects
            files = [r.to_record() for r in results]

            return files

    def delete_job(self, job_id: str):
        with self.session_maker() as session:
            session.query(JobModel).filter(JobModel.id == job_id).delete()
            session.commit()

    def get_job(self, job_id: str) -> Optional[Job]:
        with self.session_maker() as session:
            results = session.query(JobModel).filter(JobModel.id == job_id).all()
            if len(results) == 0:
                return None
            assert len(results) == 1, f"Expected 1 result, got {len(results)}"
            return results[0].to_record()

    def list_jobs(self, user_id: str) -> List[Job]:
        with self.session_maker() as session:
            results = session.query(JobModel).filter(JobModel.user_id == user_id).all()
            return [r.to_record() for r in results]

    def update_job(self, job: Job) -> Job:
        with self.session_maker() as session:
            session.query(JobModel).filter(JobModel.id == job.id).update(vars(job))
            session.commit()
        return Job

    def update_job_status(self, job_id: str, status: JobStatus):
        with self.session_maker() as session:
            session.query(JobModel).filter(JobModel.id == job_id).update({"status": status})
            if status == JobStatus.COMPLETED:
                session.query(JobModel).filter(JobModel.id == job_id).update({"completed_at": get_utc_time()})
            session.commit()
