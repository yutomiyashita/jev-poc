import os
from pathlib import Path

from dotenv import load_dotenv
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

load_dotenv(Path(__file__).resolve().with_name(".env"))
if not os.environ.get("TYPESAFE_API_KEY", "").strip():
    raise SystemExit("jev-poc直下の.envにTYPESAFE_API_KEYを設定してください。")

ticket = (
    "約20分前から、API連携ですべてのリクエストに500エラーが返るようになりました。"
    "この問題が解決するまで、顧客の注文を一件も処理できません。"
)

with TypeSafeClient(model="jev-latest") as client:  # 環境変数TYPESAFE_API_KEYを読み込みます。
    response = client.system_one(
        state=ticket,
        questions={
            "department": Choice(
                instructions="この問い合わせは、どの部署が担当すべきですか？",
                criteria={
                    "billing": "支払いやサブスクリプションに関する問題",
                    "technical": "不具合やシステム連携に関する問題",
                    "sales": "料金やアカウントに関する質問",
                },
            ),
            "frustration": Score(
                instructions="顧客はどの程度、不満を感じているように見えますか？",
                criteria=[
                    "冷静に、事実を述べている",
                    "不満はあるが、礼儀正しい",
                    "非常に怒っていて、強い言葉を使っている",
                ],
            ),
            "is_urgent": Noul(
                instructions="このメッセージは、緊急性または時間的な切迫性を伝えている",
            ),
        },
    )

department_labels = {
    "billing": "請求・支払い担当",
    "technical": "技術担当",
    "sales": "営業担当",
}
department = response.choices["department"].choice
frustration = response.scores["frustration"]

print(f"担当部署：{department_labels[department]}")
print(f"顧客の不満度（0〜2）：{frustration.score}")
print("各段階に当てはまる確率：")
for level, probability in sorted(frustration.probabilities.items()):
    print(f"  段階{level}：{frustration.legend[level]}")
    print(f"    確率：{probability}（{probability:.2%}）")

weighted_score = sum(
    level * probability for level, probability in frustration.probabilities.items()
)
formula = " + ".join(
    f"{level} × {probability}"
    for level, probability in sorted(frustration.probabilities.items())
)
print(f"返された確率から計算した加重平均：{formula} ≈ {weighted_score:.6g}")
print("スコアは各段階の番号を確率で重み付けした平均で、不満の割合（%）ではありません。")
print(f"緊急性があると判定する確率（0〜1）：{response.nouls['is_urgent'].noul}")
