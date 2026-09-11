"""backend entity layer — 跨域共享的数据 DTO(Entity)。

Domain-agnostic data shapes. 任何 service / controller / tool / mapper 都可以依赖。
Pydantic BaseModel,所有 ORM 行 ↔ DTO 通过 model_validate(...)/model_dump() 转换。

各领域私有的常量/枚举可以放在这里(单一权威),领域内不再重复定义。
"""