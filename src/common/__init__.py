"""公共层：被多条链共同调用的文件。

[公共目录] 本目录下每个文件开头都注明「被哪些链调用」。

与 src 根目录下共享文件的区别：
- 单个文件被多条链共用     → 放 src 根目录（src/ingestion.py、src/vault_io.py）
- 公共层自身成组成套       → 放本目录（state / prompts / settings / graph_registry / tools/）

链独占的文件不放这里——它们在各自的 <chain>/tools/ 与 <chain>/nodes/ 下。
依赖方向：本目录不得 import 任何链目录，唯一例外是 graph_registry.py（组合根）。
"""
