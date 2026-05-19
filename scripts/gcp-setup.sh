#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# One-time GCP setup for FinCoach CI/CD
# Run once locally: bash scripts/gcp-setup.sh
# Prerequisites: gcloud CLI installed and logged in (gcloud auth login)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_ID="fincoach-esat"
REGION="europe-west1"
SA_NAME="fincoach-deployer"
AR_REPO="fincoach"

echo "==> Setting active project to $PROJECT_ID"
gcloud config set project "$PROJECT_ID"

echo "==> Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  --project "$PROJECT_ID"

echo "==> Creating Artifact Registry repository ($AR_REPO)..."
gcloud artifacts repositories create "$AR_REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --description="FinCoach Docker images" \
  --project "$PROJECT_ID" 2>/dev/null || echo "  (already exists, skipping)"

echo "==> Creating service account ($SA_NAME)..."
gcloud iam service-accounts create "$SA_NAME" \
  --display-name="FinCoach GitHub Deployer" \
  --project "$PROJECT_ID" 2>/dev/null || echo "  (already exists, skipping)"

SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

echo "==> Granting roles to $SA_EMAIL..."
for ROLE in \
  "roles/run.admin" \
  "roles/artifactregistry.writer" \
  "roles/iam.serviceAccountUser" \
  "roles/storage.admin"; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="$ROLE" \
    --quiet
  echo "  ✓ $ROLE"
done

echo "==> Creating service account key..."
KEY_FILE="gcp-sa-key.json"
gcloud iam service-accounts keys create "$KEY_FILE" \
  --iam-account="$SA_EMAIL" \
  --project "$PROJECT_ID"

echo ""
echo "══════════════════════════════════════════════════════════════════════"
echo "  Setup complete! Now add these secrets to GitHub:"
echo "  https://github.com/EsatAkkasoglu/FinanceCoach/settings/secrets/actions"
echo ""
echo "  1. GCP_SA_KEY"
echo "     Value: contents of ./$KEY_FILE"
echo "     → cat $KEY_FILE | pbcopy   (Mac) or copy it manually"
echo ""
echo "  2. FIREBASE_SERVICE_ACCOUNT"
echo "     → Go to Firebase Console → Project Settings → Service Accounts"
echo "     → 'Generate new private key' → paste the JSON content"
echo ""
echo "  3. GEMINI_API_KEY    → your Gemini API key"
echo "  4. NEWS_API_KEY      → your NewsAPI key"
echo "  5. JWT_SECRET        → any long random string (openssl rand -hex 32)"
echo "  6. VITE_API_BASE     → leave EMPTY for now (auto-resolved from Cloud Run)"
echo ""
echo "  ⚠️  Delete $KEY_FILE after copying: rm $KEY_FILE"
echo "  ⚠️  Never commit $KEY_FILE to git!"
echo "══════════════════════════════════════════════════════════════════════"
