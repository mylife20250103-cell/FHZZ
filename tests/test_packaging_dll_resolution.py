"""构建时必须解析程序依赖，避免继承宿主工具的同名 DLL。"""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DLL 搜索规则")
def test_spec_resolves_windows_icu_and_python_openssl_with_polluted_path(tmp_path):
    pytest.importorskip("PyInstaller", reason="构建环境依赖 PyInstaller")
    project = Path(__file__).resolve().parents[1]
    ssl_dlls = sorted((Path(sys.base_prefix) / "DLLs").glob("libssl-*.dll"))
    assert len(ssl_dlls) == 1, f"无法确定当前 Python 的 OpenSSL DLL：{ssl_dlls}"
    host_tools = tmp_path / "host-tools"
    host_tools.mkdir()
    shutil.copy2(Path(os.environ["SystemRoot"]) / "System32" / "icuuc.dll", host_tools)
    shutil.copy2(ssl_dlls[0], host_tools)
    probe = r'''
import ast
import os
from pathlib import Path
import sys
from PyInstaller.depend.bindepend import resolve_library_path

project = Path(sys.argv[1])
tree = ast.parse((project / "InvoiceMergeSystem.spec").read_text(encoding="utf-8"))
# 只执行 Analysis 前的构建环境设置，不运行耗时打包或导入业务服务。
prefix = []
for statement in tree.body:
    if isinstance(statement, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "a" for target in statement.targets
    ):
        break
    prefix.append(statement)
exec(compile(ast.Module(body=prefix, type_ignores=[]), "InvoiceMergeSystem.spec", "exec"),
     {"SPECPATH": str(project)})
icu = Path(resolve_library_path("icuuc.dll")).resolve()
ssl = Path(resolve_library_path(sys.argv[2])).resolve()
assert icu.parent == (Path(os.environ["SystemRoot"]) / "System32").resolve(), str(icu)
assert ssl.parent == (Path(sys.base_prefix) / "DLLs").resolve(), str(ssl)
print("Windows ICU and Python OpenSSL resolved correctly")
'''
    # 放入有效的同架构同名 DLL，真实执行打包器的搜索，确保干净电脑也能复现。
    env = dict(os.environ)
    env["PATH"] = str(host_tools) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [sys.executable, "-c", probe, str(project), ssl_dlls[0].name],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
