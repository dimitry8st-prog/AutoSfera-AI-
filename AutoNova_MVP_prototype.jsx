
import { useState, useRef, useEffect } from "react";

// ─── KNOWLEDGE BASE (тестовые данные) ────────────────────────────────────────
const KB = {
  models: [
    { name: "Nova Comfort", type: "Седан", price: 1800000, configs: ["Base", "Standard", "Premium"] },
    { name: "Nova Drive",   type: "Кроссовер", price: 2400000, configs: ["Standard", "Premium", "Sport"] },
    { name: "Nova Cargo",   type: "Фургон",  price: 2100000, configs: ["Base", "Standard"] },
    { name: "Nova Classic", type: "Седан б/у", price: 950000, configs: [] },
  ],
  finance: {
    credit:  { minDown: 20, maxTerm: 60, rate: 9.9 },
    leasing: { minDown: 10, maxTerm: 48, rate: 8.5 },
  },
  warranty: {
    factory: "3 года или 100 000 км (при соблюдении регламента ТО)",
    body:    "6 лет (сквозная коррозия)",
    paint:   "1 год (заводской брак)",
  },
  maintenance: "Регламентное ТО каждые 15 000 км или 1 раз в год.",
  orders: {
    "АН-2024-0512": { model: "Nova Drive Premium", color: "серебристый", status: "Предпродажная подготовка", eta: "3 рабочих дня" },
    "АН-2024-0388": { model: "Nova Comfort Standard", color: "белый", status: "В пути со склада", eta: "5 рабочих дней" },
  },
};

// ─── SYSTEM PROMPTS ───────────────────────────────────────────────────────────
const SYSTEM_ORCHESTRATOR = `
Ты — AI Orchestrator компании AutoNova (вымышленная автомобильная компания, учебный проект).
Твоя задача: определить намерение пользователя и назвать агента, которому передаёшь обращение.

Агенты:
- SALES_AGENT — покупка, подбор авто, кредит, лизинг, trade-in, тест-драйв
- SUPPORT_AGENT — статус заказа, документы, общие вопросы, возврат
- SERVICE_AGENT — гарантия, ТО, запись в сервис, ремонт, эксплуатация

Правила:
1. Поздоровайся кратко и определи тему.
2. Ответь JSON строго в формате:
{"agent":"SA