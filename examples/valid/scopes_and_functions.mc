int globalCount = 2;

int main() {
    int value = add(globalCount, 3);
    {
        int globalCount = 10;
        value += globalCount;
    }
    return value;
}

int add(int a, int b) {
    return a + b;
}

