import argparse, json
from .sim import replay, metrics
def main() -> None:
    parser=argparse.ArgumentParser(description="Replay cross-venue executable spreads"); parser.add_argument("--output"); args=parser.parse_args(); result=metrics(replay())
    if args.output:
      from pathlib import Path
      d=Path(args.output); d.parent.mkdir(parents=True,exist_ok=True); d.write_text(json.dumps(result,indent=2))
    print(result)
if __name__=="__main__": main()
