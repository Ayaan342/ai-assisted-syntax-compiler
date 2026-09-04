int max(int a, int b) {
    if (a > b) {
        return a;
    } else {
        return b;
    }
}

int main() {
    int values[5];
    int sum = 0;

    for (int i = 0; i < 5; i++) {
        values[i] = i * 2;
        sum += values[i];
    }

    while (sum > 10) {
        sum--;
    }

    bool valid = sum >= 0 && sum < 100;

    if (valid) {
        return max(sum, 10);
    }

    return 0;
}

