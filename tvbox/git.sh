#!/usr/bin/env bash
# ====================================================
# 项目名称: Git Master 终端可视化管理脚本 (完整重构版 v3)
# 运行环境: Termux (bash) / MT 管理器终端 (需启动 bash 再运行)
# 核心原则: 独立执行单步操作，采用现代 Git 命令，详细注释
# v3 变更：
#   - [P0-1] CLI 路由器不再统一 exit 0，透传子命令真实退出码
#   - [P0-2] do_add 从 git add . 升级为 select-and-confirm 模式，
#            防止误暂存 __pycache__ / .backup / .operit 等私有目录
#   - [P0-3] deep_clean 拆分常规 gc 与激进清理，激进档二次确认
#   - [P0-4] undo_changes 恢复提示语义修正（git restore . 不删 untracked）
#   - [P0-5] undo_changes 选项 1/2 增加"已 push 到 remote"检测与警告
#   - [P1-1] do_one_click 改用 git pull --rebase --autostash 一行编排
#   - [P1-2] git config 默认写 local 作用域（仅当前仓库），写 global 需确认
#   - [P1-3] bind_remote 用 set-url 替代 remove+add，保住 upstream 配置
#   - [P1-4] MY_REPO_URL / LOG_FILE 支持环境变量覆盖
#   - [P1-5] log() 增加 1MB 上限 + 保留最近 500 行的简易轮转
#   - [P1-6] do_pull 移除冗余独立 fetch，消除网络往返翻倍
#   - [P2-1] DRY：require_repo / confirm / current_branch / has_staged_diff 提炼
#   - [P2-2] 移除 id -u 恒真警告，改为按需提示
#   - [P2-3] change_dir 对不存在目录改为显式询问，不再静默 mkdir
#   - [P2-4] core.quotepath=false，中文文件名不再转义
#   - [P2-5] view_status / view_logs 空列表友好提示
#   - [P3]   push 冲突优先提供 rebase 方案，force-with-lease 作为第二选项
# ====================================================

# 依赖 bash（POSIX sh 缺 local/read -p/[[ =~ ]]，MT 内置终端请先 bash）
if [ -z "${BASH_VERSION:-}" ]; then
    echo "错误: 本脚本需要 bash，请用 'bash git.sh' 运行。" >&2
    exit 1
fi

# ================= 配置区 =================
# [P1-4] 仓库地址支持环境变量 GIT_MASTER_REPO_URL 覆盖，硬编码仅作兜底
MY_REPO_URL="${GIT_MASTER_REPO_URL:-https://github.com/cluntop/tvbox.git}"
# 日志路径支持环境变量覆盖
LOG_FILE="${GIT_MASTER_LOG_FILE:-/storage/emulated/0/box/.github/git.log}"
LOG_DIR=$(dirname "$LOG_FILE")   # 全局缓存，避免每次调用 dirname

# [P1-5] 日志轮转阈值：1MB 截为最近 500 行
LOG_MAX_BYTES=1048576
LOG_KEEP_LINES=500

# [P2-1] 提交信息默认值集中定义，两处引用不散落
DEFAULT_COMMIT_MSG="Update Up"
# ================= 颜色与样式 =================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m' # 恢复默认配色

# ================= 基础核心函数 =================
# 初始化日志目录（单独执行，失败不阻塞主流程，log() 自会静默）
init_log_dir() {
    if [ ! -d "$LOG_DIR" ]; then
        mkdir -p "$LOG_DIR" 2>/dev/null
    fi
}
init_log_dir

# 统一日志记录器：带 [P1-5] 简易轮转（超 1MB 截为最近 500 行）
log() {
    if [ -f "$LOG_FILE" ]; then
        local sz
        sz=$(wc -c < "$LOG_FILE" 2>/dev/null)
        if [ "${sz:-0}" -gt "$LOG_MAX_BYTES" ]; then
            tail -n "$LOG_KEEP_LINES" "$LOG_FILE" > "$LOG_FILE.tmp" 2>/dev/null \
                && mv "$LOG_FILE.tmp" "$LOG_FILE"
        fi
    fi
    if [ -w "$LOG_DIR" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
    fi
}

# 消息函数（终端显示 + log 落盘）
success_msg() { echo -e "${GREEN}✔ $1${NC}"; log "成功: $1"; }
error_msg()   { echo -e "${RED}✘ $1${NC}"; log "错误: $1"; }
warn_msg()    { echo -e "${YELLOW}⚠ $1${NC}"; log "警告: $1"; }
info_msg()    { echo -e "${CYAN}ℹ $1${NC}"; }
title_msg()   { echo -e "\n${BOLD}${PURPLE}>>> $1 <<<${NC}\n"; }

# 依赖检查：验证 Git 是否已安装
check_git() {
    # 不走 error_msg，避免 Git 缺失时仍写脏日志
    if ! command -v git > /dev/null 2>&1; then
        echo "致命错误: 未检测到 Git 环境，请先安装 Git。" >&2
        exit 1
    fi
}

# 环境检查：当前是否处于 Git 仓库工作区内（支持子目录识别）
check_git_repo() {
    git rev-parse --is-inside-work-tree >/dev/null 2>&1
}

# [P2-1] 样板提炼：仓库守卫（原版 15 处重复）
require_repo() {
    if ! check_git_repo; then
        error_msg "当前目录非 Git 仓库，请先使用 [9] 初始化向导"
        return 1
    fi
    return 0
}

# [P2-1] 样板提炼：y/n 确认（原版 10+ 处重复）
# 用法: confirm "提示语"; 无输入时视为拒绝，避免误操作
confirm() {
    local ans
    read -r -p "$1 (y/n): " ans
    [[ "${ans:-n}" =~ ^[Yy]$ ]]
}

# [P2-1] 样板提炼：当前分支（原版 3 处重复，空则回退 main）
current_branch() {
    local b
    b=$(git branch --show-current 2>/dev/null)
    if [ -z "$b" ]; then b="main"; fi
    echo "$b"
}

# 暂存区是否有内容（git diff --cached --quiet 退出码 0=无差异）
has_staged_diff() {
    ! git diff --cached --quiet >/dev/null 2>&1
}

# 安全的分页输出：优先 less，降级直接打印
paged_output() {
    if command -v less > /dev/null 2>&1; then
        less -R
    else
        cat
    fi
}

# [P2-4] 中文/特殊字符文件名不被转义为转义序列（仅写 local，不动 global）
set_quotepath_local() {
    if check_git_repo; then
        git config --local core.quotepath false 2>/dev/null
    fi
}

# ================= 业务功能模块 =================
# 1. 暂存变动 (Git Add) — [P0-2] select-and-confirm 模式替代 git add .
do_add() {
    title_msg "📝 步骤 1/3: 暂存文件 (Git Add)"
    require_repo || return 1
    set_quotepath_local

    local changes
    changes=$(git status --porcelain 2>/dev/null)
    if [ -z "$changes" ]; then
        warn_msg "工作区纯净，没有需要暂存的修改文件。"
        return 0
    fi

    echo -e "待暂存的变更文件:"
    git status --short
    echo ""

    # [P0-2] 默认只更新已跟踪文件；untracked 需显式选择，防误提交
    echo "  1) 仅更新已跟踪文件 (git add -u) — 推荐，不会带入新私有文件"
    echo "  2) 全部暂存包括 untracked (git add .) — 所有新文件都会加入"
    echo "  3) 逐个确认 (每个文件单独询问)"
    echo "  0) 返回主菜单"
    read -r -p "请选择暂存模式: " add_mode
    case "$add_mode" in
        1)
            if git add -u; then
                success_msg "已暂存所有已跟踪文件的变更。"
            else
                error_msg "暂存失败，请检查文件权限。"
                return 1
            fi
            ;;
        2)
            warn_msg "即将把所有变更（含 untracked）加入暂存区，可能包含不应提交的私有文件。"
            if ! confirm "是否仍要全部暂存?"; then
                info_msg "已取消。"
                return 0
            fi
            if git add .; then
                success_msg "所有变更已暂存。"
            else
                error_msg "暂存失败，请检查文件权限。"
                return 1
            fi
            ;;
        3)
            # 逐行询问；文件名可能含空格，直接传给 git add --
            local staged_n=0
            while IFS= read -r line; do
                [ -z "$line" ] && continue
                local st f
                # porcelain 格式: 两位状态码 + 空格 + 文件名（长路径可能带 " 引号）
                st="${line:0:2}"
                f="${line:3}"
                # 去掉 git status 对含空格路径自动加的引号
                f="${f%\"}"; f="${f#\"}"
                echo -e "  ${CYAN}$st  $f${NC}"
                if confirm "  暂存该文件?"; then
                    if git add -- "$f" 2>/dev/null; then
                        staged_n=$((staged_n + 1))
                    else
                        warn_msg "无法暂存 $f，跳过。"
                    fi
                fi
            done <<EOF
$changes
EOF
            if [ "$staged_n" -gt 0 ]; then
                success_msg "已按选择暂存 $staged_n 个文件。"
            else
                warn_msg "未暂存任何文件。"
                return 0
            fi
            ;;
        0)
            info_msg "已取消。"
            return 0
            ;;
        *)
            error_msg "无效选项。"
            return 1
            ;;
    esac

    # [P0-2] final check：明确展示将被 commit 的文件清单
    echo ""
    echo -e "${BOLD}【暂存区当前内容 (即将被 commit 的文件)】${NC}"
    if has_staged_diff; then
        git --no-pager diff --cached --name-status
    else
        warn_msg "暂存区为空。"
    fi
    return 0
}

# 2. 创建快照 (Git Commit)
do_commit() {
    title_msg "📦 步骤 2/3: 提交快照 (Git Commit)"
    require_repo || return 1

    # 暂存区无内容则提示
    if ! has_staged_diff; then
        warn_msg "暂存区为空。请先执行 [1] 暂存文件 (Add) 再进行提交。"
        return 0
    fi

    # 提交前展示核对面，避免 commit 后才发现内容错
    echo -e "将提交的文件:"
    git --no-pager diff --cached --name-status
    echo ""

    read -r -p "请输入提交信息 (直接回车默认: $DEFAULT_COMMIT_MSG): " msg
    if [ -z "$msg" ]; then
        msg="$DEFAULT_COMMIT_MSG"
    fi
    info_msg "正在生成本地提交快照..."
    if git commit -m "$msg"; then
        success_msg "版本快照生成完毕！"
        return 0
    fi
    error_msg "提交失败，请检查配置或终端输出。"
    return 1
}

# 3. 单独执行：推送云端 (Git Push)
# [P1-3] 配套：upstream 缺失时自动 --set-upstream；
# [P3]    冲突时优先 rebase 重推，force-with-lease 降级为第二选项
do_push() {
    title_msg "🚀 步骤 3/3: 推送至云端 (Git Push)"
    require_repo || return 1

    local curr
    curr=$(current_branch)

    # upstream 缺失时首推建立跟踪关系，避免后续 push 一直缺 upstream
    if ! git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
        info_msg "当前分支无 upstream，推送并设置 origin/$curr 为上游..."
        if git push --set-upstream origin "$curr"; then
            success_msg "代码已成功同步至云端！upstream 已建立。"
            return 0
        fi
    else
        if git push origin "$curr"; then
            success_msg "代码已成功同步至云端！"
            return 0
        fi
    fi

    # 推送被拒：先尝试 rebase 保留远端新提交，force 仅作为备选
    warn_msg "常规推送被拒绝。远程仓库可能包含您本地没有的更改。"
    echo "  1) 拉取并变基后重推 (--rebase) — 推荐，保留远端提交"
    echo "  2) 安全强制推送 (--force-with-lease) — 覆盖远端该分支差异"
    echo "  3) 返回主菜单"
    read -r -p "请选择处理方式: " push_mode
    case "$push_mode" in
        1)
            info_msg "正在 git pull --rebase origin $curr 后重推..."
            if git pull --rebase origin "$curr" && git push origin "$curr"; then
                success_msg "变基后重推成功！"
                return 0
            fi
            error_msg "变基或重推失败，请先解决冲突后重试。"
            return 1
            ;;
        2)
            if ! confirm "⚠ 确认强制推送 (--force-with-lease)? (会覆盖远端差异)"; then
                info_msg "操作已取消。建议先执行拉取操作。"
                return 1
            fi
            info_msg "启动安全覆盖协议 (git push --force-with-lease) ..."
            if git push --force-with-lease --set-upstream origin "$curr"; then
                success_msg "安全强推成功！远程状态已被本地更新覆盖。"
                return 0
            fi
            error_msg "强推失败，可能存在更严重的冲突或网络问题。"
            return 1
            ;;
        3)
            info_msg "操作取消。"
            return 0
            ;;
        *)
            error_msg "无效选项。"
            return 1
            ;;
    esac
}

# 4. 拉取更新 (Git Pull)
# [P1-6] 修复双重 fetch：移除冗余的独立 fetch，git pull 自带 fetch
do_pull() {
    title_msg "📥 拉取最新更新 (Git Pull)"
    require_repo || return 1

    local curr
    curr=$(current_branch)

    # 冲突阻断机制：本地有改动时先询问 stash
    local did_stash=false
    # -uno 只看已跟踪文件改动：untracked 不会引发 pull 合并冲突，stash 也默认不含它
    if [ -n "$(git status --porcelain -uno 2>/dev/null)" ]; then
        warn_msg "检测到本地有未提交的更改，直接拉取可能导致冲突！"
        if confirm "是否先 stash 本地更改，安全拉取后自动恢复?"; then
            if ! git stash push -m "auto-stash before pull $(date '+%H:%M:%S')"; then
                error_msg "stash 失败，终止拉取以保护代码。"
                return 1
            fi
            did_stash=true
            info_msg "本地更改已存入 stash。"
        fi
    fi

    info_msg "正在下载与合并 (git pull origin $curr)..."
    local pull_out pull_status
    pull_out=$(git pull origin "$curr" 2>&1)
    pull_status=$?
    if [ $pull_status -eq 0 ]; then
        success_msg "拉取成功，本地已是最新版本。"
        if [ "$did_stash" = true ]; then
            info_msg "正在自动恢复之前暂存的代码 (git stash pop)..."
            if git stash pop; then
                success_msg "本地代码已自动恢复！"
            else
                warn_msg "自动恢复失败，可能存在合并冲突，请手动执行 git stash pop 并解决冲突。"
                return 1
            fi
        fi
        return 0
    fi
    error_msg "拉取过程产生冲突或网络连接失败。Git 报错："
    echo -e "$pull_out"
    if [ "$did_stash" = true ]; then
        warn_msg "注意：您有代码存于 stash，解决冲突后请手动执行 git stash pop。"
    fi
    return 1
}

# 5. 分支管理 (创建 / 切换 / 删除)
manage_branches() {
    title_msg "🌿 分支管理 (Branch)"
    require_repo || return 1

    echo -e "当前分支列表:"
    git branch -a
    echo ""
    echo "  1) 创建并切换至新分支"
    echo "  2) 切换到已存在的分支"
    echo "  3) 删除本地分支"
    echo "  4) 返回主菜单"
    read -r -p "请选择分支指令编号: " b_choice
    case $b_choice in
        1)
            read -r -p "请输入新分支名称 (无空格): " b_name
            if [ -z "$b_name" ]; then
                error_msg "分支名称不能为空"
                return 1
            fi
            if git switch -c "$b_name"; then
                success_msg "已创建并切换至新分支: $b_name"
                return 0
            fi
            error_msg "分支创建失败"
            return 1
            ;;
        2)
            read -r -p "请输入目标分支名称: " b_name
            if [ -z "$b_name" ]; then
                error_msg "分支名称不能为空"
                return 1
            fi
            if git switch "$b_name"; then
                success_msg "成功切换至分支: $b_name"
                return 0
            fi
            error_msg "分支切换失败"
            return 1
            ;;
        3)
            read -r -p "请输入要删除的本地分支名称: " b_name
            if [ -z "$b_name" ]; then
                error_msg "分支名称不能为空"
                return 1
            fi
            local curr
            curr=$(current_branch)
            if [ "$b_name" = "$curr" ]; then
                error_msg "无法删除当前所在分支，请先切换到其他分支。"
                return 1
            fi
            if confirm "⚠ 确认删除本地分支 '$b_name'?"; then
                if git branch -d "$b_name"; then
                    success_msg "分支 '$b_name' 已删除。"
                    return 0
                fi
                # -d 失败说明有未合并提交，追问是否强删
                warn_msg "该分支存在未合并的提交。"
                if confirm "是否强制删除 (-D，将丢失这些提交)?"; then
                    if git branch -D "$b_name"; then
                        success_msg "已强制删除分支 '$b_name'。"
                        return 0
                    fi
                fi
            fi
            return 1
            ;;
        4)
            info_msg "操作取消"
            return 0
            ;;
        *)
            error_msg "无效选项"
            return 1
            ;;
    esac
}

# 6. 状态明细（[P2-5] 空内容友好提示，不再空挂 less）
view_status() {
    title_msg "📊 库区状态剖析"
    require_repo || return 1
    set_quotepath_local

    echo -e "${BOLD}【当前文件级状态概览 (git status -s)】${NC}"
    local status_out
    status_out=$(git status -s 2>/dev/null)
    if [ -z "$status_out" ]; then
        echo "  (工作区纯净，无任何变更)"
    else
        echo "$status_out"
    fi
    echo ""

    echo -e "${BOLD}【工作区尚未暂存的代码变动 (git diff)】${NC}"
    if git diff --quiet >/dev/null 2>&1; then
        echo "  (无未暂存差异)"
    else
        git --no-pager diff | paged_output
    fi
    echo ""

    echo -e "${BOLD}【已放入暂存区待提交的代码变动 (git diff --cached)】${NC}"
    if ! has_staged_diff; then
        echo "  (暂存区为空)"
    else
        git --no-pager diff --cached | paged_output
    fi
    echo ""
    return 0
}

# 7. 历史查询（[P2-5] 空仓库友好提示）
view_logs() {
    title_msg "📜 提交历史溯源"
    require_repo || return 1

    if [ -z "$(git log -n 1 --oneline 2>/dev/null)" ]; then
        warn_msg "当前仓库尚无任何提交。"
        return 0
    fi
    git --no-pager log --graph \
        --pretty=format:'%Cred%h%Creset -%C(yellow)%d%Creset %s %Cgreen(%cr) %C(bold blue)<%an>%Creset' \
        --abbrev-commit -n 15
    echo ""
    return 0
}

# 8. 绑定远程地址（[P1-3] set-url 替代 remove+add，保住 branch.<n>.remote/.merge）
bind_remote() {
    title_msg "🔗 绑定远程仓库地址"
    require_repo || return 1

    local current_url has_origin=false
    if current_url=$(git remote get-url origin 2>/dev/null); then
        has_origin=true
    fi
    echo -e "当前设备识别到的源地址: ${CYAN}${current_url:-未绑定}${NC}"
    echo -e "脚本预设的目标源地址:   ${CYAN}$MY_REPO_URL${NC}"
    info_msg "提示: 可用环境变量 GIT_MASTER_REPO_URL 覆盖预设地址。"

    if ! confirm "确认将本地仓库指向预设目标地址吗?"; then
        info_msg "操作已取消。"
        return 0
    fi

    if [ "$has_origin" = true ]; then
        # set-url 不破坏 branch.<name>.remote/.merge 配置，push 无需重新 -u
        if git remote set-url origin "$MY_REPO_URL"; then
            success_msg "远程源地址已更新（upstream 关系已保留）！"
            return 0
        fi
        error_msg "更新远程源地址失败。"
        return 1
    fi
    if git remote add origin "$MY_REPO_URL"; then
        success_msg "远程源绑定成功！"
        return 0
    fi
    error_msg "绑定失败，请检查权限。"
    return 1
}

# 9. 初始化向导 (init + config + bind remote 三合一)
# [P1-2] 身份配置默认 local 作用域；兼容旧版 Git (< 2.28)
init_wizard() {
    title_msg "🧙 初始化向导 (Init Wizard)"
    if check_git_repo; then
        error_msg "阻止操作：当前已经是受控 Git 仓库"
        return 1
    fi

    # Step 1: git init
    info_msg "[1/3] 初始化 Git 仓库..."
    if ! git init; then
        error_msg "初始化失败"
        return 1
    fi
    # 兼容旧版 Git：通过 symbolic-ref 设置默认分支为 main
    git symbolic-ref HEAD refs/heads/main 2>/dev/null
    success_msg "仓库初始化完毕！默认分支已设为 main。"
    set_quotepath_local

    # Step 2: 用户身份配置（默认 local，出界前明确说明）
    info_msg "[2/3] 配置 Git 身份信息..."
    local cur_name cur_email
    cur_name=$(git config user.name 2>/dev/null)
    cur_email=$(git config user.email 2>/dev/null)
    echo -e "当前生效 user.name  : ${CYAN}${cur_name:-未设置}${NC}"
    echo -e "当前生效 user.email : ${CYAN}${cur_email:-未设置}${NC}"
    read -r -p "请输入 user.name  (回车跳过): " new_name
    read -r -p "请输入 user.email (回车跳过): " new_email
    if [ -n "$new_name" ] || [ -n "$new_email" ]; then
        echo "  配置作用域: 1) 当前仓库 (local, 推荐)   2) 全局 (--global)"
        read -r -p "请选择 (回车默认 local): " scope_choice
        local scope_flag="--local"
        if [ "$scope_choice" = "2" ]; then
            warn_msg "将写入全局配置，影响该用户下所有仓库。"
            if ! confirm "确认使用 global 作用域?"; then
                scope_flag="--local"
                info_msg "已回退为 local 作用域。"
            fi
        fi
        if [ -n "$new_name" ]; then
            if git config $scope_flag user.name "$new_name"; then
                success_msg "user.name 已设为: $new_name ($scope_flag)"
            fi
        fi
        if [ -n "$new_email" ]; then
            if git config $scope_flag user.email "$new_email"; then
                success_msg "user.email 已设为: $new_email ($scope_flag)"
            fi
        fi
    fi

    # Step 3: 绑定远程
    info_msg "[3/3] 绑定远程仓库..."
    echo -e "预设远程地址: ${CYAN}$MY_REPO_URL${NC}"
    if confirm "是否绑定到此地址?"; then
        # 新仓库：先试 add，被占用则改 set-url
        if git remote add origin "$MY_REPO_URL" 2>/dev/null \
           || git remote set-url origin "$MY_REPO_URL" 2>/dev/null; then
            success_msg "远程地址绑定成功！"
        else
            error_msg "远程地址绑定失败。"
        fi
    fi

    echo -e "【当前文件级状态概览 (git status -s)】"
    git status -s
    echo ""
    success_msg "🎉 初始化向导完成！可以开始使用 Add → Commit → Push 工作流了。"
    return 0
}

# 10. 切换目录（[P2-3] 目录不存在不再静默 mkdir，先询问）
change_dir() {
    title_msg "📁 切换物理工作目录"
    echo -e "当前系统位置: $(pwd)"
    read -r -p "请输入新路径 (绝对/相对均可): " new_path
    if [ -z "$new_path" ]; then
        info_msg "路径为空，未切换。"
        return 0
    fi
    if [ ! -d "$new_path" ]; then
        warn_msg "目标目录不存在: $new_path"
        if ! confirm "是否创建并进入该目录?"; then
            info_msg "切换已取消。"
            return 0
        fi
        if ! mkdir -p "$new_path" 2>/dev/null; then
            error_msg "无法创建目录: $new_path"
            return 1
        fi
    fi
    if cd "$new_path" 2>/dev/null; then
        success_msg "系统位置已成功转移至: $(pwd)"
        return 0
    fi
    error_msg "无法进入指定路径"
    return 1
}

# 11. 垃圾回收（[P0-3] 分常规 / 深度两档，深度档显示对象统计 + 二次确认）
deep_clean() {
    title_msg "🧹 垃圾回收与深度清理"
    require_repo || return 1

    # 展示对象统计，帮助用户评估要清理的内容规模
    info_msg "当前对象库统计 (git count-objects -v):"
    git count-objects -v 2>/dev/null | sed 's/^/  /'
    echo ""

    echo "  1) 常规清理 (git gc) — 安全，保留 reflog，undo 能力不受影响"
    echo "  2) 深度清理 (reflog expire + gc --aggressive --prune=now) — 不可恢复!"
    echo "  3) 返回主菜单"
    read -r -p "请选择清理级别: " clean_mode
    case "$clean_mode" in
        1)
            info_msg "正在执行常规垃圾回收 (git gc) ..."
            if git gc 2>/dev/null; then
                success_msg "常规清理成功！当前 .git 体积: $(du -sh .git 2>/dev/null | cut -f1)"
                return 0
            fi
            error_msg "清理任务中断或失败。"
            return 1
            ;;
        2)
            warn_msg "⚠ 高危：深度清理会清空全部 reflog 并物理删除 dangling 对象，"
            warn_msg "  之后一切误删找回路径（含本菜单 [14] 撤销操作）都会被切断。"
            if ! confirm "是否继续?"; then
                info_msg "操作已取消。"
                return 0
            fi
            # [P0-3] 二次确认，防止误触
            if ! confirm "⚠ 再次确认：此操作不可逆，确定继续?"; then
                info_msg "操作已取消。"
                return 0
            fi
            info_msg "正在清理历史动作残留并压缩数据库..."
            if git reflog expire --expire=now --all 2>/dev/null \
               && git gc --prune=now --aggressive 2>/dev/null; then
                success_msg "深度清理成功！当前 .git 体积: $(du -sh .git 2>/dev/null | cut -f1)"
                return 0
            fi
            error_msg "清理任务中断或失败。"
            return 1
            ;;
        3)
            info_msg "返回主菜单"
            return 0
            ;;
        *)
            error_msg "无效选项"
            return 1
            ;;
    esac
}

# 12. 统一暂存管理 (Stash 子菜单，整合 Save / Pop / Drop)
manage_stash() {
    title_msg "📦 暂存管理 (Stash)"
    require_repo || return 1

    echo -e "${BOLD}【当前暂存记录列表】${NC}"
    local stash_count
    stash_count=$(git stash list 2>/dev/null | wc -l | tr -d '[:space:]')
    if [ "$stash_count" -eq 0 ]; then
        echo "  (暂无记录)"
    else
        git --no-pager stash list
    fi
    echo ""
    echo "  1) 🗃  存入暂存 (Stash Save) — 将工作区改动压入 stash"
    echo "  2) 📤 恢复最新 (Stash Pop)  — 弹出最新一条并合并到工作区"
    echo "  3) 🗑  删除记录 (Stash Drop) — 删除指定的 stash 条目"
    echo "  4) 🔙 返回主菜单"
    read -r -p "请选择操作: " s_choice
    case $s_choice in
        1)
            # stash push 默认不含 untracked，-uno 只看已跟踪文件的改动
            if [ -z "$(git status --porcelain -uno 2>/dev/null)" ]; then
                warn_msg "没有可暂存的已跟踪文件改动（untracked 需 -u 参数，请手动操作）。"
                return 0
            fi
            read -r -p "请输入暂存备注 (回车使用默认): " stash_msg
            if [ -z "$stash_msg" ]; then
                stash_msg="manual-stash $(date '+%m-%d %H:%M')"
            fi
            if git stash push -m "$stash_msg"; then
                success_msg "当前改动已安全存入 stash: $stash_msg"
                return 0
            fi
            error_msg "存入暂存失败。"
            return 1
            ;;
        2)
            if [ "$stash_count" -eq 0 ]; then
                warn_msg "当前没有任何暂存记录。"
                return 0
            fi
            # -uno 只看已跟踪文件改动：untracked 不会与 pop 产生合并冲突
            if [ -n "$(git status --porcelain -uno 2>/dev/null)" ]; then
                warn_msg "高危拦截：工作区存在未提交的修改，此时释放 stash 可能产生冲突！"
                if ! confirm "是否仍要尝试恢复?"; then
                    info_msg "操作已安全取消。"
                    return 0
                fi
            fi
            info_msg "正在释放 stash (git stash pop)..."
            local pop_output pop_status
            pop_output=$(git stash pop 2>&1)
            pop_status=$?
            echo -e "$pop_output"
            if [ $pop_status -eq 0 ]; then
                success_msg "恢复成功！暂存代码已回到工作区。"
                return 0
            elif echo "$pop_output" | grep -q "Aborting"; then
                error_msg "恢复被 Git 中止！工作区存在冲突文件，请先提交或丢弃后再试。"
                return 1
            else
                error_msg "恢复产生合并冲突！请解决文件内的冲突标记 (<<<<<<<) 后手动提交。"
                return 1
            fi
            ;;
        3)
            if [ "$stash_count" -eq 0 ]; then
                warn_msg "当前没有任何暂存记录。"
                return 0
            fi
            echo ""
            git --no-pager stash list
            echo ""
            read -r -p "请输入要删除的编号 (如输入 0 代表 stash@{0}): " stash_idx
            if [[ "$stash_idx" =~ ^[0-9]+$ ]]; then
                if ! confirm "⚠ 确认删除 stash@{$stash_idx}? 此操作不可恢复!"; then
                    info_msg "操作已取消。"
                    return 0
                fi
                if git stash drop "stash@{$stash_idx}"; then
                    success_msg "已成功删除 stash@{$stash_idx}。"
                    return 0
                fi
                error_msg "删除失败，请确认编号是否正确。"
                return 1
            fi
            error_msg "请输入有效的数字编号。"
            return 1
            ;;
        4)
            info_msg "返回主菜单"
            return 0
            ;;
        *)
            error_msg "无效选项"
            return 1
            ;;
    esac
}

# 13. 一键同步（[P1-1] 用 pull --rebase --autostash 替代自制 stash-pop 编排）
# 流程: pull --rebase --autostash → add -u → commit → push
do_one_click() {
    title_msg "⚡ 执行一键同步工作流"
    require_repo || return 1

    local curr
    curr=$(current_branch)

    # Step 1: 拉取（autostash 自动保护本地未提交改动；rebase 使本地提交落在远端之后）
    info_msg "[1/4] 正在拉取远程更新 (git pull --rebase --autostash origin $curr)..."
    local pull_out pull_status
    pull_out=$(git pull --rebase --autostash origin "$curr" 2>&1)
    pull_status=$?
    echo -e "$pull_out"
    if [ $pull_status -ne 0 ]; then
        error_msg "拉取变基失败。"
        warn_msg "可执行 'git rebase --abort' 回到 pull 前状态，或解决冲突后 'git rebase --continue'。"
        return 1
    fi
    success_msg "拉取变基完成。"

    # Step 2: Add（[P0-2] 一致策略：只更新已跟踪文件）
    info_msg "[2/4] 正在追踪变动文件 (git add -u)..."
    if ! git add -u; then
        error_msg "暂存文件失败！"
        return 1
    fi

    # Step 3: Commit（暂存区有内容才提交）
    info_msg "[3/4] 正在生成快照 (Git Commit)..."
    if has_staged_diff; then
        if git commit -m "$DEFAULT_COMMIT_MSG"; then
            success_msg "快照已生成: $DEFAULT_COMMIT_MSG"
        else
            error_msg "提交代码失败！"
            return 1
        fi
    else
        warn_msg "没有已跟踪文件的变更，跳过提交。"
    fi

    # Step 4: Push
    info_msg "[4/4] 正在推送至云端 (Git Push)..."
    local push_out push_status
    push_out=$(git push origin "$curr" 2>&1)
    push_status=$?
    if [ $push_status -ne 0 ]; then
        error_msg "推送失败！Git 报错："
        echo -e "$push_out"
        warn_msg "可手动执行 [3] 推送云端，选择 rebase 或 force-with-lease 处理。"
        return 1
    fi
    success_msg "🎉 一键同步工作流全部执行成功！"
    return 0
}

# 14. 撤销操作 (Undo/Reset/Restore)
# [P0-4] restore . 语义修正；[P0-5] reset 前检测 commit 是否已推送
# 辅助：目标 commit 是否已在当前分支的 remote-tracking 分支上
_commit_on_remote() {
    local remote_branch
    remote_branch="origin/$(current_branch)"
    git branch -r --contains "$1" 2>/dev/null | grep -qF "$remote_branch"
}

undo_changes() {
    title_msg "↩️  撤销操作 (Undo)"
    require_repo || return 1

    echo "  1) 撤销最近一次 commit，改动退回暂存区  — git reset HEAD~1 --soft"
    echo "  2) 撤销最近一次 commit，改动退回工作区  — git reset HEAD~1 --mixed"
    echo "  3) 丢弃工作区全部未暂存改动             — git restore ."
    echo "  4) 丢弃指定文件的未暂存改动             — git restore <file>"
    echo "  5) 将指定文件移出暂存区 (取消 git add)  — git restore --staged <file>"
    echo "  6) 返回主菜单"
    echo ""
    read -r -p "请选择操作: " u_choice
    case $u_choice in
        1|2)
            # [P0-5] 该 commit 已在远端时，reset 会造成 push 分叉，先警告
            local on_remote=false
            if [ -n "$(git rev-parse --verify HEAD~1 2>/dev/null)" ] \
               && _commit_on_remote "HEAD~1"; then
                on_remote=true
                warn_msg "⚠ HEAD~1 已推送至 origin/$(current_branch)，reset 后下次 push 会因历史分叉被拒。"
                info_msg "  届时请在 [3] 推送云端中选 1) rebase 重推 或 2) force-with-lease。"
            fi
            if [ "$u_choice" = "1" ]; then
                warn_msg "将撤销最近一次 commit，改动退回暂存区 (staged)。"
                read -r -p "确认执行? (y/n): " confirm_reset
            else
                warn_msg "将撤销最近一次 commit，改动退回工作区 (unstaged)。"
                read -r -p "确认执行? (y/n): " confirm_reset
            fi
            if [[ "$confirm_reset" =~ ^[Yy]$ ]]; then
                if [ "$u_choice" = "1" ]; then
                    if git reset HEAD~1 --soft; then
                        success_msg "已撤销最近一次 commit，改动已退回暂存区。"
                        [ "$on_remote" = true ] && info_msg "提醒: 远端仍保有该 commit，下次推送前请对齐。"
                        return 0
                    fi
                else
                    if git reset HEAD~1 --mixed; then
                        success_msg "已撤销最近一次 commit，改动已退回工作区。"
                        [ "$on_remote" = true ] && info_msg "提醒: 远端仍保有该 commit，下次推送前请对齐。"
                        return 0
                    fi
                fi
                error_msg "撤销失败。"
                return 1
            fi
            info_msg "操作已取消。"
            return 0
            ;;
        3)
            # [P0-4] 文案按 git restore . 真实语义修正，并追问是否需要 clean
            warn_msg "⚠ 高危：将丢弃已跟踪文件的全部未暂存改动，且不可恢复！"
            if ! confirm "确认丢弃?"; then
                info_msg "操作已取消。"
                return 0
            fi
            if git restore .; then
                success_msg "已丢弃所有已跟踪文件的未暂存改动（untracked 文件不受影响）。"
                info_msg "提示: git restore . 不会删除 untracked 文件，如需删除请选 git clean -fd。"
                if confirm "是否同时删除所有 untracked 文件 (git clean -fd, 删除后不可恢复)?"; then
                    if git clean -fd > /dev/null 2>&1; then
                        success_msg "untracked 文件已删除。"
                    else
                        error_msg "git clean 执行失败。"
                    fi
                fi
                return 0
            fi
            error_msg "操作失败。"
            return 1
            ;;
        4)
            read -r -p "请输入要丢弃改动的文件路径: " file_path
            if [ -z "$file_path" ]; then
                error_msg "文件路径不能为空。"
                return 1
            fi
            warn_msg "⚠ 将丢弃 '$file_path' 的未暂存改动，且不可恢复！"
            if ! confirm "确认?"; then
                info_msg "操作已取消。"
                return 0
            fi
            if git restore -- "$file_path"; then
                success_msg "已丢弃 $file_path 的改动。"
                return 0
            fi
            error_msg "操作失败，请检查文件路径是否正确。"
            return 1
            ;;
        5)
            read -r -p "请输入要取消暂存的文件路径: " file_path
            if [ -z "$file_path" ]; then
                error_msg "文件路径不能为空。"
                return 1
            fi
            if git restore --staged -- "$file_path"; then
                success_msg "已将 $file_path 从暂存区移回工作区。"
                return 0
            fi
            error_msg "操作失败，请检查文件路径是否正确。"
            return 1
            ;;
        6)
            return 0
            ;;
        *)
            error_msg "无效选项"
            return 1
            ;;
    esac
}

# 15. Git 身份配置 (Config) — [P1-2] 默认 local，global 需确认
git_config() {
    title_msg "🔧 Git 身份配置 (Config)"
    if ! check_git_repo; then
        error_msg "当前目录非 Git 仓库，无法读写 local 配置。"
        return 1
    fi

    local cur_name_local cur_email_local cur_name_g cur_email_g
    # local 与 global 分开显示，未设置时明确提示回退关系
    cur_name_local=$(git config --local user.name 2>/dev/null)
    cur_email_local=$(git config --local user.email 2>/dev/null)
    echo -e "仓库 local  user.name  : ${CYAN}${cur_name_local:-未设置 (将回退全局值)}${NC}"
    echo -e "仓库 local  user.email : ${CYAN}${cur_email_local:-未设置 (将回退全局值)}${NC}"
    cur_name_g=$(git config --global user.name 2>/dev/null)
    cur_email_g=$(git config --global user.email 2>/dev/null)
    echo -e "全局 global user.name  : ${CYAN}${cur_name_g:-未设置}${NC}"
    echo -e "全局 global user.email : ${CYAN}${cur_email_g:-未设置}${NC}"
    echo ""
    echo "  1) 修改 user.name  (local, 仅当前仓库)"
    echo "  2) 修改 user.email (local, 仅当前仓库)"
    echo "  3) 修改 user.name/email (global, 需确认)"
    echo "  4) 查看当前仓库完整配置"
    echo "  5) 返回主菜单"
    read -r -p "请选择操作: " c_choice
    case $c_choice in
        1)
            read -r -p "请输入新的 user.name: " new_name
            if [ -z "$new_name" ]; then
                error_msg "名称不能为空"
                return 1
            fi
            if git config --local user.name "$new_name"; then
                success_msg "user.name (local) 已更新为: $new_name"
                return 0
            fi
            error_msg "写入失败。"
            return 1
            ;;
        2)
            read -r -p "请输入新的 user.email: " new_email
            if [ -z "$new_email" ]; then
                error_msg "邮箱不能为空"
                return 1
            fi
            if git config --local user.email "$new_email"; then
                success_msg "user.email (local) 已更新为: $new_email"
                return 0
            fi
            error_msg "写入失败。"
            return 1
            ;;
        3)
            warn_msg "⚠ 将写入全局配置 (--global)，影响该用户下所有仓库。"
            if ! confirm "确认继续?"; then
                info_msg "操作已取消。"
                return 0
            fi
            read -r -p "请输入 user.name  (回车跳过): " g_name
            read -r -p "请输入 user.email (回车跳过): " g_email
            if [ -n "$g_name" ]; then
                if git config --global user.name "$g_name"; then
                    success_msg "user.name (global) 已更新为: $g_name"
                fi
            fi
            if [ -n "$g_email" ]; then
                if git config --global user.email "$g_email"; then
                    success_msg "user.email (global) 已更新为: $g_email"
                fi
            fi
            return 0
            ;;
        4)
            echo ""
            git config --local --list 2>/dev/null
            return 0
            ;;
        5)
            return 0
            ;;
        *)
            error_msg "无效选项"
            return 1
            ;;
    esac
}

# 16. 克隆仓库 (Clone)
clone_repo() {
    title_msg "📥 克隆仓库 (Clone)"
    echo -e "预设仓库地址: ${CYAN}$MY_REPO_URL${NC}"
    echo ""
    echo "  1) 克隆到当前目录下 (自动创建子文件夹)"
    echo "  2) 克隆到指定路径"
    echo "  3) 返回主菜单"
    read -r -p "请选择操作: " cl_choice
    case $cl_choice in
        1)
            info_msg "正在克隆 $MY_REPO_URL ..."
            if git clone "$MY_REPO_URL"; then
                success_msg "克隆成功！"
                return 0
            fi
            error_msg "克隆失败，请检查网络或仓库地址。"
            return 1
            ;;
        2)
            read -r -p "请输入目标路径: " target_path
            if [ -z "$target_path" ]; then
                error_msg "路径不能为空"
                return 1
            fi
            info_msg "正在克隆到 $target_path ..."
            if git clone "$MY_REPO_URL" "$target_path"; then
                success_msg "克隆成功！目录: $target_path"
                return 0
            fi
            error_msg "克隆失败，请检查网络或路径。"
            return 1
            ;;
        3)
            return 0
            ;;
        *)
            error_msg "无效选项"
            return 1
            ;;
    esac
}

# ================= 终端前端 GUI / 菜单仪表盘 =================
show_dashboard() {
    clear 2>/dev/null || printf '\033[2J\033[H'
    echo -e "${BOLD}══════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${PURPLE}        🛠️  Git Master 控制台 (v3) ${NC}"
    echo -e "${BOLD}══════════════════════════════════════════════${NC}"
    echo -e " 📍 物理坐标: ${CYAN}$(pwd)${NC}"
    if check_git_repo; then
        local b_name changes remote
        b_name=$(current_branch)
        changes=$(git status --porcelain 2>/dev/null | wc -l | tr -d '[:space:]')
        remote=$(git remote get-url origin 2>/dev/null || echo "未绑定远程")
        echo -e " 🌿 当前分支: ${GREEN}$b_name${NC}"
        echo -e " 🔗 远程目标: ${CYAN}$remote${NC}"
        if [ "$changes" -gt 0 ]; then
            echo -e " 📝 变动预警: ${YELLOW}工作区有 $changes 个变更未处理${NC}"
        else
            echo -e " 📝 变动预警: ${GREEN}工作区完全纯净${NC}"
        fi
    else
        echo -e " ${YELLOW}⚠️  存储核心: 未检测到 Git 数据库${NC}"
    fi
    echo -e "${BOLD}──────────────────────────────────────────────${NC}"
    echo -e " [1]  📝 暂存变动   (Git Add — 可选暂存模式)"
    echo -e " [2]  📦 创建快照   (Git Commit — 提交前核对面)"
    echo -e " [3]  🚀 推送云端   (Git Push — 含 rebase/force 处理)"
    echo -e " [4]  📥 拉取更新   (Git Pull)"
    echo -e " [5]  🌿 分支管理   (Branch)"
    echo -e " [6]  📊 状态明细   (Status & Diff)"
    echo -e " [7]  📜 历史查询   (Log Graph)"
    echo -e " [8]  🔗 绑定源址   (Bind Remote — set-url 保留 upstream)"
    echo -e " [9]  🧙 初始化向导 (Init + Config + Bind)"
    echo -e " [10] 📁 切换目录   (Change Dir)"
    echo -e " [11] 🧹 垃圾回收   (Git GC — 常规/深度)"
    echo -e " [12] 📦 暂存管理   (Stash Save/Pop/Drop)"
    echo -e " [13] ⚡ 一键同步   (Pull --rebase --autostash → Add → Commit → Push)"
    echo -e " [14] ↩️  撤销操作   (Undo/Reset/Restore)"
    echo -e " [15] 🔧 身份配置   (Git Config — 默认 local)"
    echo -e " [16] 📥 克隆仓库   (Clone)"
    echo -e " [0]  ❌ 退出终端   (Exit)"
    echo -e "${BOLD}══════════════════════════════════════════════${NC}"
}

# ================= 权限前置防线 =================
# [P2-2] 移除 id -u 恒真警告（Termux 无 root 每次启动都会打印，用户会养成忽略习惯）
# 改为针对日志目录的实际写权限检测
if [ ! -w "$LOG_DIR" ]; then
    warn_msg "日志目录不可写: $LOG_DIR，本次运行将不落盘日志。"
fi
check_git

# ================= 命令行外置参数解析路由器 =================
# [P0-1] CLI 模式透传子命令真实退出码，不再统一 exit 0
if [ $# -gt 0 ]; then
    case "$1" in
        add)    do_add ;;
        commit) do_commit ;;
        push)   do_push ;;
        pull)   do_pull ;;
        branch) manage_branches ;;
        status) view_status ;;
        log)    view_logs ;;
        bind)   bind_remote ;;
        init)   init_wizard ;;
        cd)     change_dir ;;
        clean)  deep_clean ;;
        stash)  manage_stash ;;
        sync)   do_one_click ;;
        undo)   undo_changes ;;
        config) git_config ;;
        clone)  clone_repo ;;
        help|-h|--help)
            echo -e "Git Master CLI 独立模式使用指南:"
            echo -e "  add    : 暂存当前所有改动 (可选暂存模式)"
            echo -e "  commit : 为暂存的内容创建快照"
            echo -e "  push   : 将本地提交推送到远程仓库"
            echo -e "  pull   : 拉取远程最新版本"
            echo -e "  branch : 分支管理"
            echo -e "  status : 查看仓库状态"
            echo -e "  log    : 查看提交历史"
            echo -e "  bind   : 绑定远程地址 (set-url)"
            echo -e "  init   : 初始化向导 (Init + Config + Bind)"
            echo -e "  clean  : 深度清理 (可选级别)"
            echo -e "  stash  : 暂存管理 (Save/Pop/Drop)"
            echo -e "  sync   : 一键同步 (Pull --rebase --autostash)"
            echo -e "  undo   : 撤销操作 (Reset/Restore)"
            echo -e "  config : Git 身份配置 (默认 local)"
            echo -e "  clone  : 克隆仓库"
            ;;
        *)
            error_msg "未识别的参数: $1 (执行 '$0 help' 查看全部子命令)"
            exit 2
            ;;
    esac
    # 透传子命令的真实退出码
    exit $?
fi

# ================= 交互式生命周期循环 =================
while true; do
    show_dashboard
    read -r -p "👉 键入数字并回车: " choice
    # 逻辑：子菜单/查看类操作始终暂停；写操作成功后自动刷新
    require_pause=true

    case $choice in
        1)  do_add ;;
        2)  do_commit ;;
        3)  do_push ;;
        4)  do_pull ;;
        5)  manage_branches ;;
        6)  view_status ;;
        7)  view_logs ;;
        8)  bind_remote   && require_pause=false ;;
        9)  init_wizard   && require_pause=false ;;
        10) change_dir    && require_pause=false ;;
        11) deep_clean    && require_pause=false ;;
        12) manage_stash ;;
        13) do_one_click ;;
        14) undo_changes ;;
        15) git_config ;;
        16) clone_repo ;;
        0)  echo "控制台已下线。"; exit 0 ;;
        *)  error_msg "非法的选项指令，请确认您输入的数字有效" ;;
    esac

    echo ""
    if [ "$require_pause" = true ]; then
        # 失败或查看类操作时暂停，便于查阅输出
        read -r -p "按 [Enter] 键继续..."
    else
        # sleep 支持小数（GNU/BUSYbox/TOYbox 均可），原版注释理由不成立，保留 1.5 无害
        info_msg "操作成功完成，即将自动返回主菜单..."
        sleep 1.5
    fi
done