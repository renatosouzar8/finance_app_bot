
import React, { useMemo } from 'react';
import { AreaChart, Area, XAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { format, startOfMonth, endOfMonth, eachDayOfInterval, isSameDay } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import { ArrowUpCircle, ArrowDownCircle } from 'lucide-react';

const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
        const data = payload[0].payload;
        return (
            <div className="bg-slate-900/90 border border-slate-700/50 p-4 rounded-xl shadow-xl backdrop-blur-md min-w-[200px]">
                <p className="text-slate-400 text-xs mb-2">{data.fullDate ? format(data.fullDate, "d 'de' MMMM", { locale: ptBR }) : label}</p>
                <div className="mb-3">
                    <p className="text-xs text-slate-500 uppercase tracking-wider">Saldo Acumulado</p>
                    <p className={`text-lg font-bold ${data.balance >= 0 ? 'text-cyan-400' : 'text-rose-400'}`}>
                        R$ {data.balance.toFixed(2)}
                    </p>
                </div>

                {data.transactions && data.transactions.length > 0 && (
                    <div className="space-y-2 border-t border-slate-700/50 pt-2 mt-2">
                        <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Transações do dia</p>
                        {data.transactions.map((t, idx) => (
                            <div key={idx} className="flex justify-between items-center text-xs">
                                <span className="text-slate-300 truncate max-w-[120px]" title={t.description}>{t.description}</span>
                                <div className="flex items-center space-x-1">
                                    <span className={t.type === 'income' ? 'text-emerald-400' : 'text-rose-400'}>
                                        {t.type === 'income' ? '+' : '-'} R$ {(t.amount || 0).toFixed(2)}
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        );
    }
    return null;
};

const FinancialEvolutionChart = ({ transactions, currentMonth }) => {
    const data = useMemo(() => {
        if (!transactions || transactions.length === 0) return [];

        // 1. Sort transactions by date
        const sorted = [...transactions].sort((a, b) => {
            const dateA = a.date?.toDate ? a.date.toDate() : new Date(a.date);
            const dateB = b.date?.toDate ? b.date.toDate() : new Date(b.date);
            return dateA - dateB;
        });

        // 2. Generate all days in the current month range (or range of transactions)
        // Let's use the range of transactions to be dynamic, or default to current month if sparse
        if (sorted.length === 0) return [];

        const days = eachDayOfInterval({
            start: startOfMonth(currentMonth || new Date()),
            end: endOfMonth(currentMonth || new Date())
        });

        let currentBalance = 0;
        let runningData = [];

        // 3. Accumulate balance
        days.forEach(day => {
            // Find transactions for this day
            const dayTrans = sorted.filter(t => {
                const tDate = t.date?.toDate ? t.date.toDate() : new Date(t.date);
                return isSameDay(tDate, day);
            });

            // Apply net change
            const dayIncome = dayTrans.filter(t => t.type === 'income').reduce((acc, t) => acc + (t.amount || 0), 0);
            const dayExpense = dayTrans.filter(t => t.type === 'expense').reduce((acc, t) => acc + (t.amount || 0), 0);

            currentBalance += (dayIncome - dayExpense);

            runningData.push({
                date: format(day, 'dd/MM', { locale: ptBR }),
                balance: currentBalance,
                fullDate: day,
                transactions: dayTrans // Passando as transações para o tooltip
            });
        });

        return runningData;
    }, [transactions]);

    if (data.length === 0) {
        return (
            <div className="h-48 flex items-center justify-center text-slate-500 bg-slate-800/50 rounded-3xl">
                <p>Sem dados para gráfico</p>
            </div>
        );
    }

    const isPositive = data[data.length - 1]?.balance >= 0;
    const color = isPositive ? "#10b981" : "#ef4444"; // Emerald or Rose
    const gradientId = "evolutionGradient";

    return (
        <div className="w-full h-64 bg-slate-800/50 rounded-3xl p-4 shadow-lg backdrop-blur-sm border border-slate-700/50">
            <h3 className="text-slate-400 text-sm font-medium mb-2 pl-2">Evolução Patrimonial</h3>
            <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data}>
                    <defs>
                        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.4} />
                            <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                        </linearGradient>
                    </defs>
                    <XAxis
                        dataKey="date"
                        axisLine={false}
                        tickLine={false}
                        tick={{ fill: '#94a3b8', fontSize: 10 }}
                        interval="preserveStartEnd"
                        minTickGap={30}
                    />
                    <Tooltip content={<CustomTooltip />} />
                    <Area
                        type="monotone"
                        dataKey="balance"
                        stroke="#06b6d4" // Cyan-500 for a futuristic "Wealth Line"
                        strokeWidth={3}
                        fillOpacity={1}
                        fill={`url(#${gradientId})`}
                    />
                </AreaChart>
            </ResponsiveContainer>
        </div>
    );
};

export default FinancialEvolutionChart;
