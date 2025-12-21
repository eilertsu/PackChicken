# 🐔 PackChicken

**PackChicken** is a lightweight Python service that automates **Shopify order fulfillment** using the **Bring Shipping API**.  
It’s built for **full automation** — from receiving new Shopify orders to booking shipments and pushing tracking numbers back to Shopify — without relying on third-party apps like Packrooster.

---

## ✨ Features

- 📦 Automatically fetches new orders from Shopify  
- 🚚 Books shipments through the Bring API (supports both test and production environments)  
- 🔄 Updates Shopify with tracking numbers and fulfillment status  
- 💸 Works with **Shopify Basic** — no paid apps required  
- ⚙️ Simple configuration via `.env` file  
- 📬 Bring labels can be auto-downloaded after booking  

---

## 🏗️ Architecture Overview

The basic flow:

```
Shopify → PackChicken → Bring API → Shopify update
```

PackChicken connects to Shopify via the Admin API, retrieves new orders, books shipments through Bring, and sends tracking information back to Shopify automatically.

---

## ⚙️ Requirements

- Python 3.10+  
- A Shopify store (with Admin API access token)  
- Bring API key, UID, and customer number  
- Optional: none

---

## 🚀 Installation

```bash
git clone https://github.com/<yourusername>/PackChicken.git
cd PackChicken
uv sync   # or: pip install -r requirements.txt
```

---

## 🔧 Configuration

Create a `.env` file in the project root:

```bash
# Shopify
SHOPIFY_DOMAIN="https://yourshop.myshopify.com"
SHOPIFY_TOKEN="your_api_token"

# Bring
BRING_API_KEY="your_bring_api_key"
BRING_API_UID="your_bring_uid"
BRING_CUSTOMER_NUMBER="5"
BRING_TEST_INDICATOR="true"
```

---

## 🏃 Usage

Run the worker scripts manually or via systemd / supervisor:

```bash
uv run bring_fulfillment_worker.py
```

You can also run them in Docker or as background services.

---

## 🧪 Testing

To test Bring integration without real shipments:
- Set `BRING_TEST_INDICATOR="true"`
- Use Bring’s test customer numbers (5, 6, or 7)
- Create Shopify test orders in “Bogus” payment mode
- Run the standalone smoke tests:
  - Shopify orders (GraphQL): `uv run scripts/check_shopify_orders_graphql.py --first 5`
  - Bring booking: `uv run scripts/check_bring_booking.py`
- Enqueue a Shopify order as a job: `uv run scripts/enqueue_shopify_order.py --first 1`

---

## 🪵 Logging

Logs are printed to stdout and can optionally be saved to file.  
You’ll see order processing steps, API responses, and any skipped emails.

---

## 🛠️ Roadmap

- [ ] Async job queue for better scalability  
- [ ] Bring label PDF integration  
- [ ] Shopify webhook support  
- [ ] Dashboard UI  

---

## 📜 License

This project is open-source under the **MIT License** — see [LICENSE](LICENSE) for details.  
Feel free to fork, modify, and use it, but please keep attribution.

---

**Created by Eilert Sundt**
_Developed with assistance from ChatGPT (OpenAI)._
