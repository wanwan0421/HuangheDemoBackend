"""
RAG 评测启动脚本

使用方式:
  python run_eval.py --strategies no_rag vector_only --runs 1

"""

import argparse
import json
import csv
from datetime import datetime
import sys
import os

# Add current directory to sys.path to enable imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evaluator import evaluate_all_strategies, print_summary
from config import RESULT_PREFIX, STRATEGIES
import config as cfg


def save_results_to_csv(results: dict, output_prefix: str):
    """
    将结果保存为 CSV
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = f"{output_prefix}_{timestamp}.csv"
    
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "run_id",
            "date",
            "strategy",
            "total_queries",
            "recall_at_5",
            "recall_at_10",
            "recall_at_20",
            "mrr_at_10",
            "success_at_1",
            "precision_at_5",
            "precision_at_10",
            "avg_time_seconds",
            "avg_retrieval_time_seconds",
            "avg_generation_time_seconds",
            "avg_prompt_tokens",
            "avg_completion_tokens",
            "avg_total_tokens",
            "total_prompt_tokens",
            "total_completion_tokens",
            "total_tokens",
            "retrieval_success_rate",
            "generation_success_rate",
        ]
        
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for idx, (strategy_name, result) in enumerate(results.items()):
            
            row = {
                "run_id": f"run_{idx+1:03d}",
                "date": datetime.now().isoformat(),
                "strategy": strategy_name,
                "total_queries": result.get("total_queries", 0),
                "recall_at_5": result.get("recall_at_5", 0),
                "recall_at_10": result.get("recall_at_10", 0),
                "recall_at_20": result.get("recall_at_20", 0),
                "mrr_at_10": result.get("mrr_at_10", 0),
                "success_at_1": result.get("success_at_1", 0),
                "precision_at_5": result.get("precision_at_5", 0),
                "precision_at_10": result.get("precision_at_10", 0),
                "avg_time_seconds": result.get("avg_time_seconds", 0),
                "avg_retrieval_time_seconds": result.get("avg_retrieval_time_seconds", 0),
                "avg_generation_time_seconds": result.get("avg_generation_time_seconds", 0),
                "avg_prompt_tokens": result.get("avg_prompt_tokens", 0),
                "avg_completion_tokens": result.get("avg_completion_tokens", 0),
                "avg_total_tokens": result.get("avg_total_tokens", 0),
                "total_prompt_tokens": result.get("total_prompt_tokens", 0),
                "total_completion_tokens": result.get("total_completion_tokens", 0),
                "total_tokens": result.get("total_tokens", 0),
                "retrieval_success_rate": result.get("retrieval_success_rate", 0),
                "generation_success_rate": result.get("generation_success_rate", 0),
            }
            
            writer.writerow(row)
    
    print(f"\n[OK] 结果已保存到: {csv_path}")
    return csv_path


def save_detailed_results(results: dict, output_prefix: str):
    """
    保存详细结果为 JSON
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = f"{output_prefix}_{timestamp}_detailed.json"
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"[OK] 详细结果已保存到: {json_path}")
    return json_path


def main():
    parser = argparse.ArgumentParser(
        description="RAG 检索策略对比评测"
    )
    
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=["no_rag", "vector_only"],
        choices=["no_rag", "vector_only", "sparse_only", "hybrid", "hybrid_weighted", "hybrid_rrf"],
        help="要评测的策略列表"
    )
    
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="每个策略的重复运行次数"
    )
    
    parser.add_argument(
        "--queryset",
        type=str,
        default=cfg.QUERYSET_PATH,
        help="查询集 CSV 文件路径"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default=RESULT_PREFIX,
        help="结果输出文件前缀"
    )
    
    args = parser.parse_args()
    
    print("="*80)
    print("RAG 检索策略对比评测")
    print("="*80)
    print(f"策略: {', '.join(args.strategies)}")
    print(f"重复运行: {args.runs} 次")
    print(f"查询集: {args.queryset}")
    print("="*80 + "\n")
    
    try:
        # 执行评测
        results = evaluate_all_strategies(args.strategies, runs=args.runs)
        
        # 打印总结
        print_summary(results)
        
        # 保存结果
        save_results_to_csv(results, args.output)
        save_detailed_results(results, args.output)
        
        print("\n[OK] 评测完成！")
    
    except KeyboardInterrupt:
        print("\n⚠ 评测被中断")
        sys.exit(1)
    
    except Exception as e:
        print(f"\n[ERROR] 评测失败: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
