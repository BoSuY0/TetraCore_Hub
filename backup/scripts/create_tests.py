import os
from pathlib import Path

# Directories to ignore during test creation
IGNORED_DIRS = {
    ".git",
    "__pycache__",
    "venv",
    "node_modules",
    "frontend",
    "static",
    "templates",
    "logs",
    "docs",
    "examples",
    "scripts",
    "tests",
}

# Files to ignore
IGNORED_FILES = {"celery_worker.py", "celeryconfig.py"}  # These are planned for removal


def create_test_structure(source_dir: str, test_dir: str):
    """Creates a test file structure based on the existing project structure."""
    print(f"Starting to create test structure in '{test_dir}'...")

    source_path = Path(source_dir)
    test_path = Path(test_dir)
    test_path.mkdir(exist_ok=True)

    for path_object in source_path.rglob("*.py"):
        # Skip files in ignored directories
        if any(ignored in str(path_object) for ignored in IGNORED_DIRS):
            continue

        # Skip specific ignored files
        if path_object.name in IGNORED_FILES:
            continue

        # Skip __init__.py files in the root
        if path_object.name == "__init__.py" and path_object.parent == source_path:
            continue

        relative_path = path_object.relative_to(source_path)
        test_file_path = test_path / relative_path.parent / f"test_{path_object.name}"

        # Create parent directories for the test file if they don't exist
        test_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Create __init__.py in test subdirectories
        init_file = test_file_path.parent / "__init__.py"
        if not init_file.exists():
            print(f"Creating __init__.py at: {init_file}")
            init_file.touch()

        if not test_file_path.exists():
            module_path = ".".join(relative_path.with_suffix("").parts)

            content = f'''"""
Unit tests for the {module_path} module.
"""
import pytest

# TODO: Add necessary imports from '{module_path}'

def test_placeholder():
    """
    A placeholder test.
    TODO: Replace this with actual tests for the module.
    """
    assert True
'''
            print(f"Creating test file: {test_file_path}")
            test_file_path.write_text(content, encoding="utf-8")


def create_pytest_ini(root_dir: str):
    """Creates pytest.ini with base configurations."""
    content = """[pytest]
python_files = test_*.py
python_classes = Test*
python_functions = test_*

# Configure python path to recognize root modules
pythonpath = .

# Default asyncio mode
asyncio_mode = auto

# Add default markers
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: marks integration tests
    
# Add default options
addopts = -v -ra --showlocals

# Filter warnings
filterwarnings =
    ignore::DeprecationWarning
"""
    pytest_ini_path = Path(root_dir) / "pytest.ini"
    if not pytest_ini_path.exists():
        print(f"Creating {pytest_ini_path}")
        pytest_ini_path.write_text(content, encoding="utf-8")
    else:
        print(f"{pytest_ini_path} already exists. Skipping.")


def main():
    """Main function to run the script."""
    # The script is in tetra-core-hub/scripts, so project root is two levels up.
    project_root = Path(__file__).parent.parent
    source_dir = str(project_root)
    test_dir = str(project_root / "tests")

    create_test_structure(source_dir, test_dir)
    create_pytest_ini(source_dir)

    print("\\nTest structure creation complete!")
    print("Please review the generated files and start filling in the tests.")


if __name__ == "__main__":
    main()
