#!/usr/bin/env python3
"""
Pre-deployment check script for TetraCore Hub
Verifies that the project is ready for deployment to production
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

class DeploymentChecker:
    def __init__(self):
        self.project_root = Path(__file__).parent
        self.frontend_dir = self.project_root / "frontend"
        self.static_dir = self.project_root / "static"
        self.errors = []
        self.warnings = []
        self.info = []

    def check_passed(self, message):
        print(f"✅ {message}")
        self.info.append(f"PASS: {message}")

    def check_failed(self, message):
        print(f"❌ {message}")
        self.errors.append(f"FAIL: {message}")

    def check_warning(self, message):
        print(f"⚠️  {message}")
        self.warnings.append(f"WARN: {message}")

    def run_command(self, cmd, cwd=None, env=None, timeout=30):
        """Run a command and return result"""
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)

    def check_node_npm(self):
        """Check Node.js and npm installation"""
        print("\n🔍 Checking Node.js and npm...")

        # Check Node.js
        success, stdout, stderr = self.run_command(['node', '--version'])
        if success:
            version = stdout.strip()
            # Check version requirement (>=18.0.0 from package.json)
            try:
                major_version = int(version.split('.')[0].replace('v', ''))
                if major_version >= 18:
                    self.check_passed(f"Node.js {version} (meets >=18.0.0 requirement)")
                else:
                    self.check_failed(f"Node.js {version} (requires >=18.0.0)")
            except:
                self.check_warning(f"Node.js {version} (couldn't verify version requirement)")
        else:
            self.check_failed("Node.js not found or not accessible")

        # Check npm
        success, stdout, stderr = self.run_command(['npm', '--version'])
        if success:
            version = stdout.strip()
            # Check version requirement (>=9.0.0 from package.json)
            try:
                major_version = int(version.split('.')[0])
                if major_version >= 9:
                    self.check_passed(f"npm {version} (meets >=9.0.0 requirement)")
                else:
                    self.check_failed(f"npm {version} (requires >=9.0.0)")
            except:
                self.check_warning(f"npm {version} (couldn't verify version requirement)")
        else:
            self.check_failed("npm not found or not accessible")

    def check_project_structure(self):
        """Check required directories and files"""
        print("\n🔍 Checking project structure...")

        required_files = [
            ("package.json", self.project_root / "package.json"),
            ("Procfile", self.project_root / "Procfile"),
            ("requirements.txt", self.project_root / "requirements.txt"),
            ("runtime.txt", self.project_root / "runtime.txt"),
            (".buildpacks", self.project_root / ".buildpacks"),
            ("app.json", self.project_root / "app.json"),
            ("frontend/package.json", self.frontend_dir / "package.json"),
            ("frontend/tsconfig.json", self.frontend_dir / "tsconfig.json"),
        ]
        
        # Перевіряємо наявність launcher скрипта (hub_launcher.py або start_hub.py)
        launcher_found = False
        if (self.project_root / "hub_launcher.py").exists():
            self.check_passed("hub_launcher.py exists (main launcher)")
            launcher_found = True
        elif (self.project_root / "start_hub.py").exists():
            self.check_passed("start_hub.py exists (legacy launcher)")
            launcher_found = True
        else:
            self.check_failed("No launcher script found (hub_launcher.py or start_hub.py)")

        for name, path in required_files:
            if path.exists():
                self.check_passed(f"{name} exists")
                
                # Додаткова перевірка для runtime.txt
                if name == "runtime.txt":
                    with open(path, 'r') as f:
                        runtime_version = f.read().strip()
                    if runtime_version.startswith('python-'):
                        self.check_passed(f"runtime.txt specifies {runtime_version}")
                        
                        # Перевіряємо узгодженість з .python-version
                        python_version_file = self.project_root / ".python-version"
                        if python_version_file.exists():
                            with open(python_version_file, 'r') as f:
                                local_version = f.read().strip()
                            
                            # Витягуємо major.minor версії для порівняння
                            runtime_major_minor = runtime_version.replace('python-', '').split('.')[:2]
                            local_major_minor = local_version.split('.')[:2]
                            
                            if runtime_major_minor == local_major_minor:
                                self.check_passed(f"Python versions consistent: runtime.txt ({runtime_version}) matches .python-version ({local_version})")
                            else:
                                self.check_warning(f"Python version mismatch: runtime.txt ({runtime_version}) vs .python-version ({local_version})")
                    else:
                        self.check_warning(f"runtime.txt has unusual format: {runtime_version}")
            else:
                self.check_failed(f"{name} missing")

        # Check frontend source
        if (self.frontend_dir / "src").exists():
            src_files = list((self.frontend_dir / "src").rglob("*.ts*"))
            self.check_passed(f"Frontend source found ({len(src_files)} TypeScript files)")
        else:
            self.check_failed("Frontend src directory missing")

    def check_buildpacks(self):
        """Check buildpack configuration"""
        print("\n🔍 Checking buildpack configuration...")

        # Check .buildpacks file
        buildpacks_file = self.project_root / ".buildpacks"
        if buildpacks_file.exists():
            with open(buildpacks_file, 'r') as f:
                buildpacks = f.read().strip().split('\n')

            expected = [
                "https://github.com/heroku/heroku-buildpack-nodejs",
                "https://github.com/heroku/heroku-buildpack-python"
            ]

            if buildpacks == expected:
                self.check_passed(".buildpacks file correct (Node.js first, then Python)")
            else:
                self.check_failed(f".buildpacks incorrect. Expected: {expected}, Got: {buildpacks}")
        else:
            self.check_failed(".buildpacks file missing")

        # Check app.json
        app_json = self.project_root / "app.json"
        if app_json.exists():
            with open(app_json, 'r') as f:
                data = json.load(f)

            buildpacks = data.get('buildpacks', [])
            if len(buildpacks) >= 2:
                if buildpacks[0].get('url') == 'heroku/nodejs' and buildpacks[1].get('url') == 'heroku/python':
                    self.check_passed("app.json buildpacks correct")
                else:
                    self.check_failed("app.json buildpacks incorrect order (should be nodejs first, then python)")
            else:
                self.check_failed("app.json missing both buildpacks")

    def check_package_json(self):
        """Check package.json configuration"""
        print("\n🔍 Checking package.json files...")

        # Root package.json
        root_package = self.project_root / "package.json"
        if root_package.exists():
            with open(root_package, 'r') as f:
                data = json.load(f)

            scripts = data.get('scripts', {})
            required_scripts = ['heroku-prebuild', 'heroku-postbuild', 'build', 'start']

            for script in required_scripts:
                if script in scripts:
                    self.check_passed(f"Root package.json has '{script}' script")
                else:
                    self.check_failed(f"Root package.json missing '{script}' script")

            # Check heroku-postbuild specifically
            if 'heroku-postbuild' in scripts:
                if 'cd frontend && npm run build' in scripts['heroku-postbuild']:
                    self.check_passed("heroku-postbuild correctly builds frontend")
                else:
                    self.check_failed(f"heroku-postbuild incorrect: {scripts['heroku-postbuild']}")

        # Frontend package.json
        frontend_package = self.frontend_dir / "package.json"
        if frontend_package.exists():
            with open(frontend_package, 'r') as f:
                data = json.load(f)

            if 'build' in data.get('scripts', {}):
                self.check_passed("Frontend package.json has 'build' script")
            else:
                self.check_failed("Frontend package.json missing 'build' script")

    def check_procfile(self):
        """Check Procfile configuration"""
        print("\n🔍 Checking Procfile configuration...")
        
        procfile = self.project_root / "Procfile"
        if procfile.exists():
            with open(procfile, 'r') as f:
                content = f.read().strip()
            
            if 'hub_launcher.py' in content:
                self.check_passed("Procfile uses hub_launcher.py")
                if 'prod' in content:
                    self.check_passed("Procfile runs in production mode")
                else:
                    self.check_warning("Procfile doesn't specify production mode")
            elif 'start_hub.py' in content:
                self.check_warning("Procfile uses legacy start_hub.py (consider upgrading to hub_launcher.py)")
            else:
                self.check_failed("Procfile doesn't specify a valid launcher script")
        else:
            self.check_failed("Procfile missing")

    def check_typescript_config(self):
        """Check TypeScript configuration"""
        print("\n🔍 Checking TypeScript configuration...")

        # Check for the isProduction fix in config.ts
        config_file = self.frontend_dir / "src" / "config.ts"
        if config_file.exists():
            with open(config_file, 'r') as f:
                content = f.read()

            if 'const isProduction' in content or 'let isProduction' in content:
                self.check_passed("config.ts has isProduction variable defined")
            else:
                self.check_failed("config.ts missing isProduction variable")
        
        # Check for required TypeScript dependencies in frontend package.json
        frontend_package = self.frontend_dir / "package.json"
        if frontend_package.exists():
            with open(frontend_package, 'r') as f:
                data = json.load(f)
            
            dependencies = data.get('dependencies', {})
            required_types = ['@types/node', '@types/react-window']
            
            for type_pkg in required_types:
                if type_pkg in dependencies:
                    self.check_passed(f"Frontend has {type_pkg} in dependencies")
                else:
                    self.check_failed(f"Frontend missing {type_pkg} in dependencies (needed for Heroku build)")
            
            # Check if TypeScript is available for build
            if 'typescript' in dependencies or 'typescript' in data.get('devDependencies', {}):
                self.check_passed("TypeScript is available for frontend build")
            else:
                self.check_failed("TypeScript missing from frontend dependencies")

    def run_checks(self):
        """Запуск всіх перевірок"""
        print("🚀 TetraCore Hub Deployment Readiness Check")
        print("=" * 50)
        
        start_time = datetime.now()
        
        # Виконуємо всі перевірки
        self.check_node_npm()
        self.check_project_structure()
        self.check_buildpacks()
        self.check_package_json()
        self.check_procfile()
        self.check_typescript_config()
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Підсумок результатів
        print("\n" + "=" * 50)
        print("📊 ПІДСУМОК ПЕРЕВІРКИ")
        print("=" * 50)
        
        print(f"⏱️  Тривалість: {duration:.2f} секунд")
        print(f"✅ Пройдено: {len(self.info)} перевірок")
        print(f"⚠️  Попередження: {len(self.warnings)} штук")
        print(f"❌ Помилки: {len(self.errors)} штук")
        
        if self.errors:
            print("\n🔴 КРИТИЧНІ ПОМИЛКИ:")
            for error in self.errors:
                print(f"  • {error}")
        
        if self.warnings:
            print("\n🟡 ПОПЕРЕДЖЕННЯ:")
            for warning in self.warnings:
                print(f"  • {warning}")
        
        # Визначення статусу готовності
        if not self.errors:
            if not self.warnings:
                print("\n🎉 ПРОЕКТ ГОТОВИЙ ДО РОЗГОРТАННЯ!")
                return True
            else:
                print("\n✅ Проект готовий до розгортання (є попередження)")
                return True
        else:
            print("\n🛑 ПРОЕКТ НЕ ГОТОВИЙ ДО РОЗГОРТАННЯ!")
            print("   Виправте критичні помилки перед розгортанням.")
            return False


if __name__ == "__main__":
    checker = DeploymentChecker()
    success = checker.run_checks()
    
    # Вихід з відповідним кодом
    sys.exit(0 if success else 1)
