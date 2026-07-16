# Shopify Integration Setup

## Step 1: Create a Custom App

1. Log in to your **Shopify Admin** (`your-store.myshopify.com/admin`)
2. Go to **Settings → Apps and sales channels**
3. Click **Develop apps** (enable custom app development if prompted)
4. Click **Create an app**
5. Name it `WhatsApp CRM` and click **Create app**

---

## Step 2: Configure Admin API Scopes

1. In the app page, click **Configure Admin API scopes**
2. Enable the following access scopes:
   - `read_products`
   - `read_inventory`
   - `read_orders`
   - `read_customers`
3. Click **Save**

---

## Step 3: Install the App and Get Your Token

1. Click **Install app** (top-right corner)
2. Confirm by clicking **Install**
3. You'll see an **Admin API access token** — copy it immediately
   > The token is shown **only once**. If you miss it, you'll need to uninstall and reinstall the app.
4. Add to your `.env`:
   ```bash
   SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

---

## Step 4: Get Your Shop Domain

Your shop domain follows this pattern: `your-store.myshopify.com`

Add to your `.env`:
```bash
SHOPIFY_SHOP_DOMAIN=your-store.myshopify.com
```

---

## Step 5: Sync Products

Once credentials are set, sync all products to the database and vector store:

```bash
# From inside the Docker container
docker compose exec app python -m scripts.sync_products --store-id <your-store-uuid>

# Or using the setup script (first-time setup)
docker compose exec app python -m scripts.setup_store \
  --name "Your Store Name" \
  --slug "your-store" \
  --shopify-domain "your-store.myshopify.com" \
  --shopify-token "shpat_xxxx" \
  --whatsapp-phone "+919876543210"
```

---

## Step 6: Webhook Setup (Optional — Real-Time Inventory)

For real-time inventory updates when stock changes in Shopify:

1. In Shopify Admin → **Settings → Notifications** → scroll to **Webhooks**
2. Click **Create webhook**
3. Event: `Product updated`
4. Format: `JSON`
5. URL: `https://your-domain.com/webhook/shopify/products`
6. API version: Match `SHOPIFY_API_VERSION` in your `.env` (default: `2024-01`)

> Note: The Shopify webhook endpoint is not yet implemented — products are currently synced on-demand via `scripts/sync_products.py`.

---

## Testing the Connection

```bash
# Verify Shopify credentials are valid
docker compose exec app python -m scripts.health_check --shopify

# Expected output:
# ✓ Shopify [your-store]: Connected (142 products)
```

---

## Re-syncing Products

Run a full product sync at any time:

```bash
# Sync only new/changed products (faster)
docker compose exec app python -m scripts.sync_products --store-id <uuid>

# Force full re-sync (re-embeds all products)
docker compose exec app python -m scripts.sync_products --store-id <uuid> --full

# Test with sample data (no Shopify credentials needed)
docker compose exec app python -m scripts.sync_products --store-id <uuid> --mock
```

---

## Troubleshooting

| Error | Fix |
|---|---|
| `401 Unauthorized` | Token expired or wrong scope. Uninstall and reinstall the app. |
| `404 Not Found` | Wrong `SHOPIFY_SHOP_DOMAIN`. Check spelling (no `https://`). |
| `OPENAI_API_KEY not set` | Embeddings require OpenAI. Set `OPENAI_API_KEY` in `.env`. |
| Products not appearing in search | Run `sync_products.py` — products must be in Qdrant to be searchable. |
