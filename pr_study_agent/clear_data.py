"""清空已生成的技能数据（三层结构 + patch pool）。"""

import shutil
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
SKILLS_DIR = DATA_DIR / "skills"


def clear_patch_pool():
    pool_dir = SKILLS_DIR / "patch_pool"
    if not pool_dir.exists():
        print("patch_pool 目录不存在，跳过")
        return
    removed = 0
    for item in pool_dir.glob("*.json"):
        item.unlink()
        removed += 1
    print(f"已清空 patch_pool：删除 {removed} 个 patch 文件")


def clear_references():
    refs_dir = SKILLS_DIR / "references"
    if not refs_dir.exists():
        print("references 目录不存在，跳过")
        return
    shutil.rmtree(refs_dir)
    refs_dir.mkdir(parents=True, exist_ok=True)
    print("已清空 references 目录")


def clear_skill_md():
    skill_md = SKILLS_DIR / "SKILL.md"
    if skill_md.exists():
        skill_md.unlink()
        print("已删除 SKILL.md")
    else:
        print("SKILL.md 不存在，跳过")


def clear_logs():
    log_dir = DATA_DIR / "study_logs"
    if not log_dir.exists():
        print("study_logs 目录不存在，跳过")
        return
    removed = 0
    for item in log_dir.glob("*.json"):
        item.unlink()
        removed += 1
    print(f"已清空 study_logs：删除 {removed} 个日志文件")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="清空已生成的技能数据")
    parser.add_argument("--patches-only", action="store_true", help="只清空 patch pool")
    parser.add_argument("--refs-only", action="store_true", help="只清空 references")
    parser.add_argument("--logs-only", action="store_true", help="只清空日志")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过确认直接执行")
    args = parser.parse_args()

    if args.patches_only:
        target = "patch pool"
    elif args.refs_only:
        target = "references"
    elif args.logs_only:
        target = "study logs"
    else:
        target = "所有数据 (SKILL.md + references + patch_pool + logs)"

    if not args.yes:
        confirm = input(f"确定要清空 {target} 吗？此操作不可撤销 [y/N]: ").strip().lower()
        if confirm != "y":
            print("已取消")
            exit(0)

    if args.patches_only:
        clear_patch_pool()
    elif args.refs_only:
        clear_references()
    elif args.logs_only:
        clear_logs()
    else:
        clear_skill_md()
        clear_references()
        clear_patch_pool()
        clear_logs()

    print("完成")
