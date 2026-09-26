import json


def build_io_pairs(data):
    messages = data.get("messages", [])
    pairs = []
    current_input = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role in {"system", "user", "tool"}:
            item = {"role": role}
            if isinstance(content, str) and content.strip():
                item["content"] = content.strip()
            if item.get("content"):
                current_input.append(item)

        elif role == "assistant":
            output = {}

            if isinstance(content, str) and content.strip():
                output["content"] = content.strip()

            if msg.get("tool_calls"):
                output["tool_calls"] = []
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    output["tool_calls"].append({
                        "name": fn.get("name"),
                        "arguments": fn.get("arguments")
                    })

            if output:
                pairs.append({
                    "input": current_input.copy(),
                    "output": output
                })
                current_input = []

    return pairs


def main():

    instance_id = "astropy__astropy-13398"

    with open(f"output_swebench/{instance_id}/{instance_id}.traj.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    pairs = build_io_pairs(data)

    with open(f"output_swebench/{instance_id}/{instance_id}.simple.json", "w", encoding="utf-8") as f:
        json.dump(pairs, f, ensure_ascii=False, indent=2)

    print("已保存到 io_pairs.json")


if __name__ == "__main__":
    main()