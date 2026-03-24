from prompt_optimizer.diff_utils import combine_diff_sources, extract_changed_paths


def test_extract_changed_paths_single_file():
    diff = """diff --git a/app.py b/app.py
index 123..456 100644
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-print("old")
+print("new")
"""
    assert extract_changed_paths(diff) == ["app.py"]


def test_extract_changed_paths_multiple_files_and_rename():
    diff = """diff --git a/src/old_name.py b/src/new_name.py
similarity index 80%
rename from src/old_name.py
rename to src/new_name.py
--- a/src/old_name.py
+++ b/src/new_name.py
diff --git a/tests/test_app.py b/tests/test_app.py
--- a/tests/test_app.py
+++ b/tests/test_app.py
"""
    assert extract_changed_paths(diff) == [
        "src/old_name.py",
        "src/new_name.py",
        "tests/test_app.py",
    ]


def test_extract_changed_paths_empty_diff():
    assert extract_changed_paths("") == []


def test_combine_diff_sources():
    combined = combine_diff_sources(
        "diff --git a/a.py b/a.py",
        [("b.diff", "diff --git a/b.py b/b.py")],
    )
    assert "a.py" in combined
    assert "Uploaded diff: b.diff" in combined

