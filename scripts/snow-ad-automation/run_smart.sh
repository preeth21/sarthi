#!/bin/bash
# ==============================================================================
# run_smart.sh — Smart wrapper for ServiceNow AD Group Request Automation
# ==============================================================================
#
# Automatically decides which underlying script to use and how to iterate,
# based on the ratio of users to groups provided:
#
#   users > groups  →  Multi-User strategy
#                      (run_multi_user.sh once per group, all users each time)
#                      Iterates over the SMALLER set (groups) = fewer sessions
#
#   groups > users  →  Multi-Group strategy
#                      (run_multi_group.sh once per user, all groups each time)
#                      Iterates over the SMALLER set (users) = fewer sessions
#
#   users == groups →  Default: Multi-Group strategy (iterate over users)
#
# Does NOT modify run_multi_group.sh or run_multi_user.sh — calls them as-is.
#
# Usage:
#   ./run_smart.sh --groups "G1,G2,G3" --users "u1,u2" --justification "reason"
#   ./run_smart.sh -g "G1,G2" -u "u1,u2,u3" -j "reason" --dry-run
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ------------------------------------------------------------------------------
# Parse arguments
# NOTE: Avoid bash reserved variable names (GROUPS, USERS are reserved in bash)
# Using AD_GROUPS, AD_USERS, JUSTIF as safe internal variable names
# ------------------------------------------------------------------------------
AD_GROUPS=""
AD_USERS=""
JUSTIF=""
DRY_RUN=""
TIMEOUT_ARG=""
HEADLESS_ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --groups|-g)
            AD_GROUPS="$2"; shift 2 ;;
        --users|-u)
            AD_USERS="$2"; shift 2 ;;
        --justification|-j)
            JUSTIF="$2"; shift 2 ;;
        --dry-run)
            DRY_RUN="--dry-run"; shift ;;
        --timeout)
            TIMEOUT_ARG="--timeout $2"; shift 2 ;;
        --headless)
            HEADLESS_ARG="--headless"; shift ;;
        --help|-h)
            echo "Usage: ./run_smart.sh --groups \"G1,G2,...\" --users \"u1,u2,...\" --justification \"reason\" [--dry-run] [--timeout N]"
            exit 0 ;;
        *)
            echo "❌ Unknown option: $1"
            echo "   Run ./run_smart.sh --help for usage"
            exit 1 ;;
    esac
done

# ------------------------------------------------------------------------------
# Validate required arguments
# ------------------------------------------------------------------------------
if [[ -z "$AD_GROUPS" || -z "$AD_USERS" || -z "$JUSTIF" ]]; then
    echo "❌ Missing required arguments."
    echo "   Required: --groups, --users, --justification"
    echo "   Usage: ./run_smart.sh --groups \"G1,G2\" --users \"u1,u2\" --justification \"reason\""
    exit 1
fi

# ------------------------------------------------------------------------------
# Split into arrays and count
# ------------------------------------------------------------------------------
IFS=',' read -ra GROUP_ARRAY <<< "$AD_GROUPS"
IFS=',' read -ra USER_ARRAY  <<< "$AD_USERS"

# Trim whitespace using bash built-ins (safe for emails/special chars)
TRIMMED_GROUPS=()
for g in "${GROUP_ARRAY[@]}"; do
    g="${g#"${g%%[![:space:]]*}"}"   # trim leading whitespace
    g="${g%"${g##*[![:space:]]}"}"   # trim trailing whitespace
    TRIMMED_GROUPS+=("$g")
done

TRIMMED_USERS=()
for u in "${USER_ARRAY[@]}"; do
    u="${u#"${u%%[![:space:]]*}"}"   # trim leading whitespace
    u="${u%"${u##*[![:space:]]}"}"   # trim trailing whitespace
    TRIMMED_USERS+=("$u")
done

NUM_GROUPS=${#TRIMMED_GROUPS[@]}
NUM_USERS=${#TRIMMED_USERS[@]}

# ------------------------------------------------------------------------------
# Print summary
# ------------------------------------------------------------------------------
echo "============================================================"
echo "🤖 ServiceNow AD Group Request — Smart Wrapper"
echo "============================================================"
echo "  Groups (${NUM_GROUPS}): ${TRIMMED_GROUPS[*]}"
echo "  Users  (${NUM_USERS}): ${TRIMMED_USERS[*]}"
echo "  Justification: ${JUSTIF:0:60}..."
echo "  Mode: ${DRY_RUN:-Live}"
echo "============================================================"

# ------------------------------------------------------------------------------
# Strategy decision — always iterate over the SMALLER set to minimise sessions
# ------------------------------------------------------------------------------
if [[ "$NUM_USERS" -gt "$NUM_GROUPS" ]]; then

    # More users than groups → iterate over groups (smaller set)
    # Multi-User: all users → 1 group per session  |  sessions = NUM_GROUPS
    echo ""
    echo "📊 Strategy: MULTI-USER  (${NUM_USERS} users > ${NUM_GROUPS} groups)"
    echo "   Iterating over the smaller set: ${NUM_GROUPS} group(s)"
    echo "   Each session: all ${NUM_USERS} users → 1 group  |  Total sessions: ${NUM_GROUPS}"
    echo "   Script: run_multi_user.sh"
    echo "============================================================"

    TOTAL=${#TRIMMED_GROUPS[@]}
    COUNT=0

    for GROUP in "${TRIMMED_GROUPS[@]}"; do
        COUNT=$((COUNT + 1))
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "🔄 Session [${COUNT}/${TOTAL}] — Group: ${GROUP}"
        echo "   Adding users: ${AD_USERS}"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        "$SCRIPT_DIR/run_multi_user.sh" \
            --groups "$GROUP" \
            --users  "$AD_USERS" \
            --justification "$JUSTIF" \
            $DRY_RUN $TIMEOUT_ARG $HEADLESS_ARG

        if [[ $COUNT -lt $TOTAL ]]; then
            echo ""
            echo "  ✅ Session ${COUNT}/${TOTAL} complete. Starting next in 3 seconds..."
            sleep 3
        fi
    done

elif [[ "$NUM_GROUPS" -gt "$NUM_USERS" ]]; then

    # More groups than users → iterate over users (smaller set)
    # Multi-Group: 1 user → all groups per session  |  sessions = NUM_USERS
    echo ""
    echo "📊 Strategy: MULTI-GROUP  (${NUM_GROUPS} groups > ${NUM_USERS} users)"
    echo "   Iterating over the smaller set: ${NUM_USERS} user(s)"
    echo "   Each session: 1 user → all ${NUM_GROUPS} groups  |  Total sessions: ${NUM_USERS}"
    echo "   Script: run_multi_group.sh"
    echo "============================================================"

    TOTAL=${#TRIMMED_USERS[@]}
    COUNT=0

    for USER in "${TRIMMED_USERS[@]}"; do
        COUNT=$((COUNT + 1))
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "🔄 Session [${COUNT}/${TOTAL}] — User: ${USER}"
        echo "   Adding to groups: ${AD_GROUPS}"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        "$SCRIPT_DIR/run_multi_group.sh" \
            --groups "$AD_GROUPS" \
            --users  "$USER" \
            --justification "$JUSTIF" \
            $DRY_RUN $TIMEOUT_ARG $HEADLESS_ARG

        if [[ $COUNT -lt $TOTAL ]]; then
            echo ""
            echo "  ✅ Session ${COUNT}/${TOTAL} complete. Starting next in 3 seconds..."
            sleep 3
        fi
    done

else

    # Equal counts — default to Multi-Group, iterate over users
    echo ""
    echo "📊 Strategy: EQUAL counts (${NUM_USERS} users = ${NUM_GROUPS} groups)"
    echo "   Default: MULTI-GROUP — iterating over users"
    echo "   Each session: 1 user → all ${NUM_GROUPS} groups  |  Total sessions: ${NUM_USERS}"
    echo "   Script: run_multi_group.sh"
    echo "============================================================"

    TOTAL=${#TRIMMED_USERS[@]}
    COUNT=0

    for USER in "${TRIMMED_USERS[@]}"; do
        COUNT=$((COUNT + 1))
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "🔄 Session [${COUNT}/${TOTAL}] — User: ${USER}"
        echo "   Adding to groups: ${AD_GROUPS}"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        "$SCRIPT_DIR/run_multi_group.sh" \
            --groups "$AD_GROUPS" \
            --users  "$USER" \
            --justification "$JUSTIF" \
            $DRY_RUN $TIMEOUT_ARG $HEADLESS_ARG

        if [[ $COUNT -lt $TOTAL ]]; then
            echo ""
            echo "  ✅ Session ${COUNT}/${TOTAL} complete. Starting next in 3 seconds..."
            sleep 3
        fi
    done

fi

# ------------------------------------------------------------------------------
# Final summary
# ------------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "✅ All sessions completed!"
echo "   Total groups : ${NUM_GROUPS}"
echo "   Total users  : ${NUM_USERS}"
echo "============================================================"
