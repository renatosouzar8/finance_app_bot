import React, { useMemo } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';

const COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#06b6d4', '#f43f5e', '#84cc16', '#a855f7', '#14b8a6', '#f97316', '#3b82f6'];

const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
        const data = payload[0].payload;
        return (
            <div className="bg-slate-900/90 border border-slate-700/50 p-3 rounded-xl shadow-xl backdrop-blur-md">
                <p className="text-slate-200 font-medium mb-1">{data.name}</p>
                <div className="flex items-center space-x-2">
                    <span className="w-3 h-3 rounded-full" style={{ backgroundColor: data.fill }}></span>
                    <span className="text-slate-300">R$ {data.value.toFixed(2)}</span>
                </div>
                <p className="text-xs text-slate-500 mt-1">{(data.percent * 100).toFixed(1)}% do total</p>
            </div>
        );
    }
    return null;
};

const FinancialCategoryChart = ({ transactions }) => {
    const data = useMemo(() => {
        if (!transactions || transactions.length === 0) return [];

        const expenses = transactions.filter(t => t.type === 'expense');
        const grouped = expenses.reduce((acc, t) => {
            const cat = t.category || 'Outros';
            acc[cat] = (acc[cat] || 0) + (t.amount || 0);
            return acc;
        }, {});

        const total = Object.values(grouped).reduce((a, b) => a + b, 0);

        return Object.entries(grouped)
            .map(([name, value], index) => ({
                name,
                value,
                percent: value / total,
                fill: COLORS[index % COLORS.length]
            }))
            .sort((a, b) => b.value - a.value); // Sort max to min
    }, [transactions]);

    if (data.length === 0) {
        return (
            <div className="h-64 flex flex-col items-center justify-center text-slate-500 bg-slate-800/50 rounded-3xl border border-slate-700/50">
                <p>Sem despesas para exibir o gráfico</p>
            </div>
        );
    }

    return (
        <div className="w-full h-80 bg-slate-800/50 rounded-3xl p-4 shadow-lg backdrop-blur-sm border border-slate-700/50 flex flex-col">
            <h3 className="text-slate-400 text-sm font-medium mb-2 pl-2">Despesas por Categoria</h3>
            <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                    <Pie
                        data={data}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={80}
                        paddingAngle={5}
                        dataKey="value"
                        stroke="none"
                    >
                        {data.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.fill} />
                        ))}
                    </Pie>
                    <Tooltip content={<CustomTooltip />} />
                    <Legend
                        layout="vertical"
                        verticalAlign="middle"
                        align="right"
                        iconType="circle"
                        wrapperStyle={{ fontSize: '12px', color: '#94a3b8' }}
                    />
                </PieChart>
            </ResponsiveContainer>
        </div>
    );
};

export default FinancialCategoryChart;
