from Backend.DBMS.indexes.rtree import Rtree
import random
import os

N = 100

def main():
    data_file = os.path.join("Backend/DBMS/data", "RtreeFile.bin")
    if os.path.exists(data_file):
        os.remove(data_file)

    r = Rtree()

    random.seed(42)
    points = [(random.uniform(-1000, 1000), random.uniform(-1000, 1000)) for _ in range(N)]

    for i, p in enumerate(points):
        ok = r.insert(p, (i, 0))
        print(f"Insert {i}: {p} -> {ok}")

    range_res = r.rangeSearch((5, 10), 300.0)
    print("Range search result (len):", range_res)

    knn_res = r.knnSearch((5, 10), 3)
    print("KNN result:", knn_res)

    for p in points[:5]:
        ok = r.remove(p)
        print(f"Remove {p} -> {ok}")

    img = r.visualize()
    print("Visual saved to:", img)


if __name__ == "__main__":
    main()
