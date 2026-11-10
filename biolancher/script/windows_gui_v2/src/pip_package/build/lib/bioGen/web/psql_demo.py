import os
import sqlalchemy as sa
from sqlalchemy import create_engine, Column, Text, ForeignKey, Boolean, Integer, ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import sessionmaker

# 定义 Base
Base = declarative_base()


#### SEE https://docs.chainlit.io/data-layers/sqlalchemy
### INITIAL SCHEMA FOR CHAINLIT
# 用户表
class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True)
    identifier = Column(Text, nullable=False, unique=True)
    metadata_ = Column('metadata', JSONB, nullable=False)
    createdAt = Column(Text)

# 线程表
class Thread(Base):
    __tablename__ = "threads"
    id = Column(UUID(as_uuid=True), primary_key=True)
    createdAt = Column(Text)
    name = Column(Text)
    userId = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    userIdentifier = Column(Text)
    tags = Column(ARRAY(Text))
    metadata_ = Column('metadata', JSONB)

# 步骤表（添加缺失的 defaultOpen 和 disableFeedback 列）
class Step(Base):
    __tablename__ = "steps"
    id = Column(UUID(as_uuid=True), primary_key=True)
    name = Column(Text, nullable=False)
    type = Column(Text, nullable=False)
    threadId = Column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    parentId = Column(UUID(as_uuid=True))
    streaming = Column(Boolean, nullable=False)
    waitForAnswer = Column(Boolean)
    isError = Column(Boolean)
    metadata_ = Column('metadata', JSONB)
    tags = Column(ARRAY(Text))
    input = Column(Text)
    output = Column(Text)
    createdAt = Column(Text)
    command = Column(Text)
    start = Column(Text)
    end = Column(Text)
    generation = Column(JSONB)
    showInput = Column(Text)
    language = Column(Text)
    indent = Column(Integer)
    defaultOpen = Column(Boolean)  # 新添加的缺失列
    disableFeedback = Column(Boolean)  # 可选添加，常见缺失列，允许 NULL

# 元素表
class Element(Base):
    __tablename__ = "elements"
    id = Column(UUID(as_uuid=True), primary_key=True)
    threadId = Column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"))
    type = Column(Text)
    url = Column(Text)
    chainlitKey = Column(Text)
    name = Column(Text, nullable=False)
    display = Column(Text)
    objectKey = Column(Text)
    size = Column(Text)
    page = Column(Integer)
    language = Column(Text)
    forId = Column(UUID(as_uuid=True))
    mime = Column(Text)
    props = Column(JSONB)

# 反馈表
class Feedback(Base):
    __tablename__ = "feedbacks"
    id = Column(UUID(as_uuid=True), primary_key=True)
    forId = Column(UUID(as_uuid=True), nullable=False)
    threadId = Column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    value = Column(Integer, nullable=False)
    comment = Column(Text)

# 主函数：连接数据库并创建表
if __name__ == "__main__":
    # 替换为你的连接 URL（或从环境变量读取）
    DATABASE_URL = "postgresql://postgres:biogendata@127.0.0.1:5432/chainlit_db"
    # DATABASE_URL = os.getenv("DATABASE_URL")  # 更安全的方式

    engine = create_engine(DATABASE_URL, echo=True)  # echo=True 显示 SQL 日志

    # 删除现有表（警告：会丢失数据！）
    #print("Dropping existing tables...")
    Base.metadata.drop_all(engine)  # 自动处理外键依赖
    #print("Existing tables dropped!")

    # 创建所有表
    Base.metadata.create_all(engine)

    # 检查表
    Session = sessionmaker(bind=engine)
    session = Session()
    print("Database initialized successfully! Tables created:")
    print([table.name for table in Base.metadata.tables.values()])
    session.close()