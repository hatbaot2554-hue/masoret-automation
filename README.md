# מדריך הפעלה — אוטומציית המרכז למסורת יהודית

---

## מה יש כאן

| קובץ | מה הוא עושה |
|------|-------------|
| `scraper/scrape_products.py` | סורק את האתר של אבא כל יום ומעדכן מוצרים |
| `order-bot/place_order.py` | ממלא הזמנה באתר של אבא אוטומטית |
| `order-bot/webhook_server.py` | מחכה להזמנות מהאתר החדש ומפעיל את הרובוט |
| `.github/workflows/daily-scrape.yml` | מריץ את הסריקה כל יום בענן (חינמי) |

---

## שלב 1: העלאה ל-GitHub

1. היכנס ל- https://github.com
2. לחץ "New repository" — שם: `masoret-automation`
3. העלה את כל התיקייה הזו

---

## שלב 2: הגדרת סריקה יומית אוטומטית

הסריקה כבר מוגדרת! GitHub יריץ אותה כל יום בשעה 6:00 בבוקר.

לבדיקה ידנית: GitHub → Actions → "סריקה יומית" → "Run workflow"

---

## שלב 3: הגדרת שרת הזמנות (Railway — חינמי)

1. היכנס ל- https://railway.app
2. "New Project" → "Deploy from GitHub" → בחר את ה-repo
3. הגדר משתני סביבה (Environment Variables):

```
GMAIL_USER=המייל-שלך@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
NOTIFY_EMAIL=המייל-שלך@gmail.com
DISCOUNT_CODE=קוד-הנחה-אם-יש
```

**איך מקבלים Gmail App Password:**
1. כנס ל- myaccount.google.com
2. אבטחה → אימות דו-שלבי (הפעל אם לא פעיל)
3. חיפוש "סיסמאות לאפליקציות"
4. צור סיסמה חדשה — העתק אותה

---

## שלב 4: חיבור לאתר Next.js

בקובץ `.env.local` של האתר החדש, הוסף:

```
AUTOMATION_WEBHOOK_URL=https://שם-הפרויקט.railway.app/webhook/new-order
```

ובקובץ `app/api/orders/route.js` — הקוד כבר מוכן לשלוח לשם!

---

## איך זה עובד בפועל

```
לקוח מזמין באתר החדש
        ↓
האתר גובה תשלום (Stripe/PayPlus)
        ↓
שולח webhook לשרת
        ↓
הרובוט נכנס לאתר של אבא
        ↓
ממלא פרטים + קוד הנחה
        ↓
שולח הזמנה
        ↓
שולח לך מייל: "יש להעביר ₪X"
        ↓
אתה מעביר 30 שניות מהבנק
```

---

## קוד הנחה עתידי

כשתקבל קוד הנחה מאבא, פשוט עדכן ב-Railway:
`DISCOUNT_CODE=הקוד-החדש`

הרובוט יזין אותו אוטומטית בכל הזמנה.

---

## שאלות?

כל שינוי — שלח לקלוד!
