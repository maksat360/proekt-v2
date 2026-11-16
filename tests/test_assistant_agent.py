# -*- coding: utf-8 -*-
"""Джарвис-агент: модель зовёт инструменты по шагам; права, «да» и приватность — на стороне портала.
Облако не вызывается: ответы модели подменены."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assistant  # noqa: E402

CFG = {"base": "https://x", "key": "k", "model": "m"}
SECS = [{"id": "wh", "label": "Склад"}]


def call(name, **args):
    return {"content": "", "tool_calls": [{"id": "c1", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}


def say(text):
    return {"content": text}


class AgentTests(unittest.TestCase):
    def run_agent(self, steps, tools, text="вопрос"):
        seen = []

        def fake(cfg, messages, spec, limit):
            seen.append(messages[-1])
            return steps.pop(0)
        with mock.patch.object(assistant, "_chat_cloud_tools", fake):
            res = assistant._agent(CFG, "Тест Тестов", "Начальник", text, SECS, None, tools, [])
        return res, seen

    def test_chains_tools_then_answers(self):
        tools = {"order_detail": ("заказ", {"номер": {"type": "string"}}, lambda номер="": f"заказ №{номер}: модель 479"),
                 "model_info": ("модель", {"модель": {"type": "string"}}, lambda модель="": f"{модель}: спецификации нет")}
        res, seen = self.run_agent([call("order_detail", номер="3"), call("model_info", модель="479"),
                                    say("Заказ №3 стоит: у модели 479 нет спецификации, сэр.")], tools)
        self.assertIn("479 нет спецификации", res["ответ"])
        self.assertEqual([m["content"] for m in seen[1:]], ["заказ №3: модель 479", "479: спецификации нет"])
        self.assertIn("агент", res["модель"])

    def test_change_needs_yes(self):
        done = []
        tools = {"revision_start": ("ревизия", {"запрос": {"type": "string"}},
                                    lambda запрос="": done.append(1) or "начата", lambda запрос="": "Начать ревизию?")}
        res, _ = self.run_agent([call("revision_start", запрос="постель")], tools)
        self.assertEqual(done, [])
        self.assertEqual(res["подтвердить"]["действие"], "revision_start")

    def test_no_access_and_open_only_own_sections(self):
        res, seen = self.run_agent([call("salary_all"), call("open_section", id="users"), call("open_section", id="wh"),
                                    say("Открываю склад, сэр.")], {})
        self.assertIn("нет доступа", seen[1]["content"])
        self.assertIn("нет", seen[2]["content"])
        self.assertEqual(res["открыть"], "wh")

    def test_private_data_not_sent_to_cloud(self):
        tools = {"salary": ("зарплата", {}, lambda: "Иванова 15000")}
        with mock.patch.object(assistant, "_answer_with_data", return_value={"ответ": "локально"}) as local:
            res, seen = self.run_agent([call("salary")], tools)
        local.assert_called_once()
        self.assertEqual(res["ответ"], "локально")
        self.assertFalse(any("15000" in str(m.get("content")) for m in seen))

    def test_navigation_filter_passed_to_page(self):
        tools = {"show_stock": ("склад", {"запрос": {"type": "string"}},
                                lambda запрос="": {"ответ": "открываю", "открыть": "wh", "фильтр": {"cat": ["Постель"]}})}
        res, _ = self.run_agent([call("show_stock", запрос="постель"), say("Открыл склад, сэр.")], tools)
        self.assertEqual((res["открыть"], res["фильтр"]), ("wh", {"cat": ["Постель"]}))


if __name__ == "__main__":
    unittest.main()
